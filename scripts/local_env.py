"""Load a settings file's Values into the environment (local scripts only).

Default src/local.settings.json (emulators). TRIAGE_SETTINGS=src/azure.settings.json points the same scripts at the
deployed Azure stack (written by scripts/azure_settings.py: endpoints and names only, Entra ID via `az login`).
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def settings_file() -> Path:
    return Path(os.environ.get("TRIAGE_SETTINGS", ROOT / "src" / "local.settings.json"))


def load() -> None:
    values = json.loads(settings_file().read_text())["Values"]
    for key, value in values.items():
        os.environ.setdefault(key, value)
