"""The Helm chart (D30): what it may never render, read from its templates (the chart job renders them)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy" / "chart" / "ticket-triage"
TEMPLATES = {p.name: p.read_text() for p in (CHART / "templates").iterdir()}


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_the_chart_never_renders_a_secret_or_a_reachable_service(name):
    text = TEMPLATES[name]
    assert not re.search(r"^kind: Secret\b", text, re.M), "secrets are the platform's (D30)"
    assert "type: NodePort" not in text and "type: LoadBalancer" not in text


def test_every_pod_uses_the_image_by_digest_and_no_api_token():
    helpers = TEMPLATES["_helpers.tpl"]
    assert "{{ .Values.image.repository }}@{{ $digest }}" in helpers
    assert 'regexMatch "^sha256:[0-9a-f]{64}$"' in helpers
    assert "automountServiceAccountToken: false" in helpers
    images = [m for text in TEMPLATES.values() for m in re.findall(r"image: (.+)", text)]
    assert images and set(images) == {'{{ include "ticket-triage.image" $root }}'}


def test_the_worker_has_no_replica_count():
    """KEDA owns it: a replicas field would reset the worker on every apply."""
    worker = TEMPLATES["deployment-worker.yaml"]
    deployment = worker.split("---")[0]
    assert "replicas:" not in deployment


def test_the_lab_stub_sends_the_event_grid_system_key():
    """A Functions host in a container checks the webhook key (func start doesn't): the stub sends it, D30."""
    lab = TEMPLATES["lab.yaml"]
    assert '"keyEnv": "NOTIFY_WEBHOOK_KEY"' in lab and "key: host.systemKey.eventgrid_extension" in lab
