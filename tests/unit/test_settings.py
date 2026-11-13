"""Settings that choose an Azure path: email transport and the chat request shape."""

import pytest

from triage import settings

MAIL = {"EMAIL_SENDER": "bot@x.example", "ESCALATION_MAILBOX": "e@x.example", "REVIEW_MAILBOX": "r@x.example"}


@pytest.fixture
def env(monkeypatch):
    for name in ("EMAIL_TRANSPORT", "ACS_ENDPOINT", "CHAT_REASONING_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in MAIL.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_smtp_is_the_default_transport(env):
    cfg = settings.notify()
    assert cfg.transport == "smtp" and cfg.acs_endpoint is None


def test_acs_transport_needs_an_endpoint(env):
    env.setenv("EMAIL_TRANSPORT", "acs")
    with pytest.raises(RuntimeError, match="ACS_ENDPOINT"):
        settings.notify()
    env.setenv("ACS_ENDPOINT", "https://acs-x.uae.communication.azure.com")
    assert settings.notify().acs_endpoint == "https://acs-x.uae.communication.azure.com"


def test_unknown_transport_is_rejected(env):
    env.setenv("EMAIL_TRANSPORT", "sendgrid")
    with pytest.raises(RuntimeError, match="EMAIL_TRANSPORT"):
        settings.notify()


@pytest.mark.parametrize(("value", "expected"), [(None, None), ("", None), ("low", "low")])
def test_reasoning_effort_empty_means_classic_model(env, value, expected):
    env.setenv("CHAT_MODEL", "m")
    if value is not None:
        env.setenv("CHAT_REASONING_EFFORT", value)
    assert settings.triage().reasoning_effort == expected
