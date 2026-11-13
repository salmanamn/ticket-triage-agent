"""Terraform (Azure) and the code/emulators (local) must describe the same contracts.

Locally the app creates the knowledge container itself (triage.cosmos.ensure_kb_container) and the Service Bus
emulator reads emulators/servicebus/config.json; on Azure Terraform creates both. These tests fail when one side
changes without the other.
"""

import json
import re
from pathlib import Path

from triage.cosmos import kb_policies

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "infra" / "modules" / "cosmos" / "knowledge-container.json"
STACK_VARIABLES = ROOT / "infra" / "modules" / "stack" / "variables.tf"


def knowledge_resource() -> dict:
    template = json.loads(TEMPLATE.read_text())
    (container,) = [
        r for r in template["resources"] if r["type"] == "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers"
    ]
    return template, container["properties"]["resource"]


def tf_default(variable: str) -> str:
    """Default of a variable in infra/modules/stack/variables.tf (simple scalar defaults only)."""
    block = re.search(rf'variable "{variable}" \{{(.*?)\n\}}', STACK_VARIABLES.read_text(), re.DOTALL)
    assert block, f"variable {variable} not found"
    default = re.search(r"^\s*default\s*=\s*(\S+)", block.group(1), re.MULTILINE)
    assert default, f"variable {variable} has no default"
    return default.group(1)


def test_knowledge_container_matches_code_policies():
    template, resource = knowledge_resource()
    dims = template["parameters"]["dimensions"]["defaultValue"]
    vector_policy, indexing_policy = kb_policies(dims)

    embeddings = [dict(e, dimensions=dims) for e in resource["vectorEmbeddingPolicy"]["vectorEmbeddings"]]
    assert embeddings == vector_policy["vectorEmbeddings"]
    assert resource["indexingPolicy"] == indexing_policy
    assert resource["partitionKey"]["paths"] == ["/kind"]


def test_embedding_dimensions_agree_everywhere():
    template, resource = knowledge_resource()
    (embedding,) = resource["vectorEmbeddingPolicy"]["vectorEmbeddings"]
    assert embedding["dimensions"] == "[parameters('dimensions')]"  # Terraform passes var.embedding_dimensions
    local = json.loads((ROOT / "src" / "local.settings.json.example").read_text())["Values"]
    assert int(tf_default("embedding_dimensions")) == template["parameters"]["dimensions"]["defaultValue"]
    assert int(tf_default("embedding_dimensions")) == int(local["EMBEDDING_DIMENSIONS"])


def test_max_delivery_count_matches_emulator_and_app():
    config = json.loads((ROOT / "emulators" / "servicebus" / "config.json").read_text())
    (queue,) = config["UserConfig"]["Namespaces"][0]["Queues"]
    local = json.loads((ROOT / "src" / "local.settings.json.example").read_text())["Values"]
    assert int(tf_default("max_delivery_count")) == queue["Properties"]["MaxDeliveryCount"]
    assert int(tf_default("max_delivery_count")) == int(local["TRIAGE_MAX_ATTEMPTS"])


def test_every_required_setting_is_an_azure_app_setting():
    """A setting the code _require()s but the stack doesn't set crashes the Function on Azure (not locally)."""
    required = set(re.findall(r'_require\("(\w+)"\)', (ROOT / "src" / "triage" / "settings.py").read_text()))
    stack = (ROOT / "infra" / "modules" / "stack" / "main.tf").read_text()
    set_by_stack = set(re.findall(r"^\s*(\w+)\s+=", stack, re.MULTILINE))
    assert {"OPENAI_BASE_URL", "ACS_ENDPOINT", "REVIEW_MAILBOX"} <= required  # the regex still finds them
    assert required - set_by_stack == set()
