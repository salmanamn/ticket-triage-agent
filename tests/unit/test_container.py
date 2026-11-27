"""The container image (D28): what the Dockerfile and the image check must keep true."""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_image", ROOT / "scripts" / "check_image.py")
check_image = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_image)
DOCKERFILE = (ROOT / "Dockerfile").read_text()


def test_base_image_is_pinned_by_digest():
    (line,) = [entry for entry in DOCKERFILE.splitlines() if entry.startswith("FROM ")]
    assert re.fullmatch(r"FROM mcr\.microsoft\.com/azure-functions/python:4-python3\.13@sha256:[0-9a-f]{64}", line)


def test_image_runs_as_a_fixed_user_on_8080():
    assert re.search(r"^USER 10001:10001$", DOCKERFILE, re.M)
    assert "ASPNETCORE_URLS=http://+:8080" in DOCKERFILE


def test_packages_go_where_the_python_3_13_worker_looks():
    assert "--target /home/site/wwwroot/.python_packages/lib/site-packages -r /tmp/requirements.txt" in DOCKERFILE


def test_only_the_app_and_the_lab_tools_are_in_the_build_context():
    ignore = [entry for entry in (ROOT / ".dockerignore").read_text().splitlines() if entry and entry[0] != "#"]
    assert ignore[0] == "*"  # everything is excluded first
    assert {"!src/", "!scripts/fake_llm.py", "!scripts/eventgrid_stub.py"} == {p for p in ignore if p.startswith("!")}
    assert {"src/local.settings.json", "src/local.settings.json.example", "src/azure.settings.json"} <= set(ignore)


def test_host_keys_cover_every_function_and_the_event_grid_webhook():
    functions = ["submit_ticket", "health", "queue_depth_report", "triage_ticket", "notify_ticket"]
    keys = check_image.host_keys(functions)
    assert {"host.master", "host.function.default", "host.function.keda", "host.systemKey.eventgrid_extension"} <= set(
        keys
    )
    assert {f"functions.{f}.default" for f in functions} <= set(keys)
    assert len(set(keys.values())) == len(keys) and all(len(v) >= 40 for v in keys.values())


def test_the_image_check_expects_what_the_app_registers():
    assert check_image.expected_functions() == sorted(
        ["submit_ticket", "health", "queue_depth_report", "triage_ticket", "notify_ticket"]
    )


def test_pinning_rewrites_only_the_from_line():
    spec = importlib.util.spec_from_file_location("pin_base_image", ROOT / "scripts" / "pin_base_image.py")
    pin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pin)
    digest = "sha256:" + "a" * 64
    text = "# base\nFROM mcr.microsoft.com/azure-functions/python:4-python3.13\nUSER 10001:10001\n"
    once = pin.pinned(text, digest)
    assert once == f"# base\nFROM mcr.microsoft.com/azure-functions/python:4-python3.13@{digest}\nUSER 10001:10001\n"
    assert pin.pinned(once, "sha256:" + "b" * 64).count("@sha256:") == 1
    with pytest.raises(SystemExit):
        pin.base("FROM a:1\nFROM b:2\n")
