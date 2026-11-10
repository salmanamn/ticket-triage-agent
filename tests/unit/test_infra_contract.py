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
