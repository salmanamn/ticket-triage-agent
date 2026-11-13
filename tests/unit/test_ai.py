"""Chat request shape: classic models (Ollama) vs reasoning models (Azure gpt-5.x, D19)."""

from types import SimpleNamespace

import pytest

from triage.ai import ModelOutputError, OpenAIChatModel
from triage.models import TRIAGE_JSON_SCHEMA


class RecordingClient:
    def __init__(self, content='{"ok": true}', finish_reason="stop"):
        self.kwargs = None
        reply = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))]
        )
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._reply = reply

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return self._reply


def call(model, temperature=0.4):
    return model.complete_json(system="s", user="u", schema=TRIAGE_JSON_SCHEMA, name="t", temperature=temperature)


def test_classic_model_gets_temperature_and_max_tokens():
    client = RecordingClient()
    call(OpenAIChatModel("phi4-mini:3.8b", client=client, max_tokens=700))
    assert client.kwargs["temperature"] == 0.4 and client.kwargs["max_tokens"] == 700
    assert "reasoning_effort" not in client.kwargs and "max_completion_tokens" not in client.kwargs


def test_reasoning_model_gets_effort_and_completion_budget_but_no_temperature():
    client = RecordingClient()
    call(OpenAIChatModel("gpt-5.4-mini", client=client, max_tokens=4000, reasoning_effort="low"))
    assert client.kwargs["reasoning_effort"] == "low" and client.kwargs["max_completion_tokens"] == 4000
    assert "temperature" not in client.kwargs and "max_tokens" not in client.kwargs


def test_both_paths_keep_strict_structured_output():
    for effort in (None, "low"):
        client = RecordingClient()
        call(OpenAIChatModel("m", client=client, reasoning_effort=effort))
        assert client.kwargs["response_format"]["type"] == "json_schema"
        assert client.kwargs["response_format"]["json_schema"]["strict"] is True


def test_truncation_still_raises_for_reasoning_models():
    client = RecordingClient(content=None, finish_reason="length")
    with pytest.raises(ModelOutputError, match="truncated"):
        call(OpenAIChatModel("gpt-5.4-mini", client=client, reasoning_effort="low"))
