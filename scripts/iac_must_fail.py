#!/usr/bin/env python3
"""IaC must fail: break one property of a real plan at a time and require the Conftest gate to reject it.

The input is `terraform show -json` of the full-stack plan (infra/envs/local, -var full_stack=true). The
unmodified plan must pass; every mutation must produce at least one `deny`. A mutation whose target resource
is missing from the plan is STALE (update it together with the Terraform). Stdlib only; needs conftest on PATH.

Usage: python3 scripts/iac_must_fail.py <plan.json> [--policy infra/policy] [--list]
"""

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_OTHER = "/subscriptions/x/resourceGroups/rg-x/providers/Microsoft.OperationalInsights/workspaces/law-x"
OWNER = "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"
DEADLETTER_CONTAINER = "eventgrid-deadletter"


@dataclass(frozen=True)
class Mutation:
    name: str
    type: str  # resource type to change (the first instance in the plan)
    apply: Callable[[dict], None]  # mutates rc["change"]["after"] (or the plan, for type "<plan>")


def setter(key: str, value) -> Callable[[dict], None]:
    def run(after: dict) -> None:
        after[key] = value

    return run


def template_replace(old: str, new: str) -> Callable[[dict], None]:
    def run(after: dict) -> None:
        if old not in after["template_content"]:
            raise LookupError(old)
        after["template_content"] = after["template_content"].replace(old, new)

    return run


def drop_cosmos_diagnostics(plan: dict) -> None:
    before = len(plan["resource_changes"])
    plan["resource_changes"] = [
        rc
        for rc in plan["resource_changes"]
        if not (rc["type"] == "azurerm_monitor_diagnostic_setting" and ".module.cosmos" in rc["address"])
    ]
    if len(plan["resource_changes"]) == before:
        raise LookupError("cosmos diagnostic setting")


def add_setting(name: str) -> Callable[[dict], None]:
    def run(plan: dict) -> None:
        plan["output_changes"]["summary"]["after"]["app_setting_names"].append(name)

    return run


def acs_local_auth_on(plan: dict) -> None:
    for rc in plan["resource_changes"]:
        content = (rc["change"]["after"] or {}).get("template_content") or ""
        if "Microsoft.Communication/communicationServices" in content:
            if '"disableLocalAuth":true' not in content:
                raise LookupError("disableLocalAuth in the ACS template")
            rc["change"]["after"]["template_content"] = content.replace(
                '"disableLocalAuth":true', '"disableLocalAuth":false'
            )
            return
    raise LookupError("ACS template deployment")


def openai_subdomain_removed(plan: dict) -> None:
    """As if custom_subdomain_name were deleted from the module: null and no longer 'known after apply'."""
    for rc in plan["resource_changes"]:
        if rc["type"] == "azurerm_cognitive_account" and rc["change"]["after"] is not None:
            rc["change"]["after"]["custom_subdomain_name"] = None
            rc["change"].get("after_unknown", {}).pop("custom_subdomain_name", None)
            return
    raise LookupError("azurerm_cognitive_account")


def deadletter_into_host_storage(plan: dict) -> None:
    """As if the dead-letter container were created in the Function App's host storage account again (D24 -> D25)."""
    containers = [
        rc for rc in plan["resource_changes"] if rc["type"] == "azurerm_storage_container" and rc["change"]["after"]
    ]
    dead = [rc for rc in containers if rc["change"]["after"]["name"] == DEADLETTER_CONTAINER]
    host = [rc for rc in containers if rc["change"]["after"]["name"] != DEADLETTER_CONTAINER]
    if not dead or not host:
        raise LookupError("dead-letter container and host container")
    dead[0]["module_address"] = host[0]["module_address"]


def deadletter_to_host_container(after: dict) -> None:
    destinations = after.get("storage_blob_dead_letter_destination") or []
    if not destinations:
        raise LookupError("storage_blob_dead_letter_destination")
    destinations[0]["storage_blob_container_name"] = "app-package"


def provisioned_sku(after: dict) -> None:
    after["sku"][0]["name"] = "GlobalProvisionedManaged"


def role_to_owner(after: dict) -> None:
    after["role_definition_id"] = after["role_definition_id"].rsplit("/", 1)[0] + "/" + OWNER


MUTATIONS = [
    Mutation("servicebus-sas-keys", "azurerm_servicebus_namespace", setter("local_auth_enabled", True)),
    Mutation("servicebus-basic-tier", "azurerm_servicebus_namespace", setter("sku", "Basic")),
    Mutation("queue-no-duplicate-detection", "azurerm_servicebus_queue", setter("requires_duplicate_detection", False)),
    Mutation("queue-delivery-count-drift", "azurerm_servicebus_queue", setter("max_delivery_count", 10)),
    Mutation("cosmos-account-keys", "azurerm_cosmosdb_account", setter("local_authentication_enabled", True)),
    Mutation(
        "cosmos-no-vector-search", "azurerm_cosmosdb_account", setter("capabilities", [{"name": "EnableServerless"}])
    ),
    Mutation(
        "knowledge-flat-index",
        "azurerm_resource_group_template_deployment",
        template_replace('"type":"diskANN"', '"type":"flat"'),
    ),
    Mutation(
        "knowledge-embedding-indexed",
        "azurerm_resource_group_template_deployment",
        template_replace('{"path":"/embedding/*"}', '{"path":"/other/*"}'),
    ),
    Mutation("eventgrid-topic-keys", "azurerm_eventgrid_topic", setter("local_auth_enabled", True)),
    Mutation("eventgrid-legacy-schema", "azurerm_eventgrid_topic", setter("input_schema", "EventGridSchema")),
    Mutation(
        "notify-no-deadletter",
        "azurerm_eventgrid_event_subscription",
        setter("storage_blob_dead_letter_destination", []),
    ),
    Mutation(
        "notify-deadletter-to-host-container", "azurerm_eventgrid_event_subscription", deadletter_to_host_container
    ),
    Mutation("deadletter-shares-host-storage", "<plan>", deadletter_into_host_storage),
    Mutation("storage-shared-key", "azurerm_storage_account", setter("shared_access_key_enabled", True)),
    Mutation("storage-public-blobs", "azurerm_storage_account", setter("allow_nested_items_to_be_public", True)),
    Mutation(
        "function-basic-auth-publish",
        "azurerm_function_app_flex_consumption",
        setter("webdeploy_publish_basic_authentication_enabled", True),
    ),
    Mutation(
        "function-storage-connection-string",
        "azurerm_function_app_flex_consumption",
        setter("storage_authentication_type", "StorageAccountConnectionString"),
    ),
    Mutation("function-http-allowed", "azurerm_function_app_flex_consumption", setter("https_only", False)),
    Mutation("appinsights-local-auth", "azurerm_application_insights", setter("local_authentication_enabled", True)),
    Mutation(
        "diagnostics-other-workspace",
        "azurerm_monitor_diagnostic_setting",
        setter("log_analytics_workspace_id", WORKSPACE_OTHER),
    ),
    Mutation("diagnostics-missing", "<plan>", drop_cosmos_diagnostics),
    Mutation("role-owner", "azurerm_role_assignment", role_to_owner),
    Mutation("openai-api-keys", "azurerm_cognitive_account", setter("local_auth_enabled", True)),
    Mutation("openai-no-subdomain", "<plan>", openai_subdomain_removed),
    Mutation("openai-provisioned-throughput", "azurerm_cognitive_deployment", provisioned_sku),
    Mutation("acs-access-keys", "<plan>", acs_local_auth_on),
    Mutation("role-to-user", "azurerm_role_assignment", setter("principal_type", "User")),
    Mutation("setting-connection-string", "<plan>", add_setting("ServiceBusConnection")),
    Mutation("setting-api-key", "<plan>", add_setting("OPENAI_API_KEY")),
]


def conftest(plan: dict, policy: Path) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(plan, fh)
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            ["conftest", "test", "--no-color", "--policy", str(policy), fh.name],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        Path(fh.name).unlink()
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    fails = [line.split(" - main - ", 1)[-1] for line in lines if line.startswith("FAIL")]
    if fails:
        return proc.returncode, fails[0]
    return proc.returncode, lines[-1] if lines else proc.stderr.strip()[-200:]


def mutate(plan: dict, m: Mutation) -> dict:
    out = copy.deepcopy(plan)
    if m.type == "<plan>":
        m.apply(out)
        return out
    for rc in out["resource_changes"]:
        if rc["type"] == m.type and rc["change"]["after"] is not None:
            m.apply(rc["change"]["after"])
            return out
    raise LookupError(m.type)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path, nargs="?")
    parser.add_argument("--policy", type=Path, default=ROOT / "infra" / "policy")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list or not args.plan:
        for m in MUTATIONS:
            print(f"{m.name:36} {m.type}")
        return 0 if args.list else 2

    plan = json.loads(args.plan.read_text())
    code, summary = conftest(plan, args.policy)
    if code != 0:
        print(f"ERROR    baseline: the unmodified plan fails the gate ({summary})")
        return 1
    print(f"OK       baseline: {summary}")

    problems = 0
    for m in MUTATIONS:
        try:
            mutated = mutate(plan, m)
        except LookupError as exc:
            print(f"STALE    {m.name:36} {exc} not in the plan; update the mutation")
            problems += 1
            continue
        code, summary = conftest(mutated, args.policy)
        if code != 0:
            print(f"DENIED   {m.name:36} {summary}")
        else:
            print(f"ALLOWED  {m.name:36} the gate passed it: add or fix a policy rule")
            problems += 1
    print(f"{len(MUTATIONS) - problems}/{len(MUTATIONS)} mutations denied")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
