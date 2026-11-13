#!/usr/bin/env python3
"""Write src/azure.settings.json for the laptop scripts (seed_kb, search_kb, eval_triage, show_triage) from the
deployed stack's Terraform output. Endpoints and names only: the scripts authenticate as you (`az login`), with the
operator data roles the stack grants (Cosmos Data Contributor on db triage, Cognitive Services OpenAI User).

Usage: python3 scripts/azure_settings.py      (after `./scripts/iac.sh plan-azure` has initialised infra/envs/azure)
Then:  TRIAGE_SETTINGS=src/azure.settings.json PYTHONPATH=src uv run python scripts/seed_kb.py
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "azure.settings.json"


def main() -> int:
    proc = subprocess.run(  # noqa: S603 - fixed argv
        ["terraform", "-chdir=infra/envs/azure", "output", "-json", "summary"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr.strip() or "terraform output failed", file=sys.stderr)
        return 1
    summary = json.loads(proc.stdout)
    values = summary.get("client_settings") or {}
    if not values.get("COSMOS_ENDPOINT"):
        print("client_settings is empty: is the stack deployed (ci-deploy.sh apply)?", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps({"IsEncrypted": False, "Values": values}, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {', '.join(sorted(values))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
