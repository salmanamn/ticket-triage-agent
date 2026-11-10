"""Tests must fail: apply known-bad changes one at a time and require the unit tests to catch each one.

Each mutation breaks one safety property the project depends on (fraud floor, injection handling, idempotency,
no customer text in headers or events, structured output, ...). The script works on a temporary copy of the repo,
so the working tree is never modified. Exit 1 when a mutation survives (tests still pass), when its anchor text
is no longer in the code (update the mutation together with the code), or when the clean copy fails.

Usage: uv run python scripts/tests_must_fail.py [--only NAME] [--list]
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = ("src", "tests", "scripts", "kb", "eval", "pyproject.toml")
SUMMARY = re.compile(r"(\d+) failed")


@dataclass(frozen=True)
class Mutation:
    name: str
    file: str
    old: str
    new: str
    tests: str  # pytest target that must fail


MUTATIONS = [
    Mutation(
        "fraud-floor-removed",
        "src/triage/agent.py",
        'if fraud and PRIORITIES.index(decision.priority) < PRIORITIES.index("high"):',
        "if False:",
        "tests/unit/test_agent.py",
    ),
    Mutation(
        "injection-not-stripped",
        "src/triage/agent.py",
        "        if INJECTION_PATTERN.search(sentence):",
        "        if False:",
        "tests/unit/test_agent.py",
    ),
    Mutation(
        "injection-may-reach-critical",
        "src/triage/agent.py",
        'if injection_suspected and not fraud and decision.priority == "critical":',
        "if False:",
        "tests/unit/test_agent.py",
    ),
    Mutation(
        "invented-sources-kept",
        "src/triage/agent.py",
        "cited = [s for s in dict.fromkeys(decision.sources) if s in known]",
        "cited = list(decision.sources)",
        "tests/unit/test_agent.py",
    ),
    Mutation(
        "redelivery-retriaged",
        "src/triage/agent.py",
        'if existing and existing.get("status") == "triaged":',
        "if False:",
        "tests/unit/test_agent.py",
    ),
    Mutation(
        "first-attempt-not-deterministic",
        "src/triage/agent.py",
        "temperature=0.0 if attempt <= 1 else RETRY_TEMPERATURE,",
        "temperature=RETRY_TEMPERATURE,",
        "tests/unit/test_agent.py",
    ),
    Mutation(
        "structured-output-dropped",
        "src/triage/ai.py",
        'response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},',
        "",
        "tests/unit/test_fake_llm.py",
    ),
    Mutation(
        "message-id-not-ticket-id",
        "src/triage/ingest.py",
        "message_id=message.ticket_id,",
        'message_id=f"{message.ticket_id}-{id(message)}",',
        "tests/unit/test_ingest.py",
    ),
    Mutation(
        "validation-error-echoes-input",
        "src/triage/ingest.py",
        '"message": err["msg"]}',
        "\"message\": f\"{err['msg']}: {data.get(err['loc'][0])}\"}",
        "tests/unit/test_ingest.py",
    ),
    Mutation(
        "customer-email-in-event",
        "src/triage/events.py",
        'data=data.model_dump(mode="json"),',
        'data={**data.model_dump(mode="json"), "customer_email": record.customer_email},',
        "tests/unit/test_events.py",
    ),
    Mutation(
        "event-republished",
        "src/triage/events.py",
        "if record.event_published_at and not force:",
        "if False:",
        "tests/unit/test_events.py",
    ),
    Mutation(
        "injection-routed-as-escalation",
        "src/triage/notify.py",
        "    if record.injection_suspected:\n",
        "    if False:\n",
        "tests/unit/test_notify.py",
    ),
    Mutation(
        "duplicate-email-sent",
        "src/triage/notify.py",
        "if record.notification is not None:",
        "if False:",
        "tests/unit/test_notify.py",
    ),
    Mutation(
        "customer-text-in-mail-subject",
        "src/triage/notify.py",
        'subject = f"[{priority}] Ticket {record.ticket_id} - {record.category}"',
        'subject = f"[{priority}] Ticket {record.ticket_id} - {record.category}: {record.subject}"',
        "tests/unit/test_notify.py",
    ),
    Mutation(
        "stub-retries-bad-request",
        "scripts/eventgrid_stub.py",
        "NO_RETRY = {400, 413}",
        "NO_RETRY = set()",
        "tests/unit/test_eventgrid_stub.py",
    ),
]


def make_copy(dest: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "local.settings.json")
    for name in COPY:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=ignore)
        else:
            shutil.copy2(src, dest / name)


def pytest(cwd: Path, target: str) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not integration", target]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)  # noqa: S603 - fixed argv
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, lines[-1] if lines else proc.stderr.strip()[-200:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="run a single mutation by name")
    parser.add_argument("--list", action="store_true", help="list the mutations and exit")
    args = parser.parse_args()
    mutations = [m for m in MUTATIONS if not args.only or m.name == args.only]
    if args.list or not mutations:
        for m in MUTATIONS:
            print(f"{m.name:34} {m.file}")
        return 0 if args.list else 2

    with tempfile.TemporaryDirectory(prefix="tests-must-fail-") as tmp:
        work = Path(tmp)
        make_copy(work)
        code, summary = pytest(work, "tests/unit")
        if code != 0:
            print(f"ERROR    baseline: unit tests fail on the unmodified copy ({summary})")
            return 1
        print(f"OK       baseline: {summary}")

        problems = 0
        for m in mutations:
            path = work / m.file
            original = path.read_text()
            if original.count(m.old) != 1:
                print(f"STALE    {m.name:34} anchor found {original.count(m.old)}x in {m.file}; update the mutation")
                problems += 1
                continue
            path.write_text(original.replace(m.old, m.new))
            try:
                code, summary = pytest(work, m.tests)
            finally:
                path.write_text(original)
            if code == 1 and SUMMARY.search(summary):
                print(f"KILLED   {m.name:34} {m.tests} ({SUMMARY.search(summary).group(0)})")
            elif code == 0:
                print(f"SURVIVED {m.name:34} {m.tests} still passes: add a test for this behaviour")
                problems += 1
            else:
                print(f"ERROR    {m.name:34} pytest exit {code} (not a test failure): {summary}")
                problems += 1

    killed = len(mutations) - problems
    print(f"{killed}/{len(mutations)} mutations killed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
