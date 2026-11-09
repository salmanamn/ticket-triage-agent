"""Load src/local.settings.json Values into the environment (local scripts only)."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load() -> None:
    values = json.loads((ROOT / "src" / "local.settings.json").read_text())["Values"]
    for key, value in values.items():
        os.environ.setdefault(key, value)
