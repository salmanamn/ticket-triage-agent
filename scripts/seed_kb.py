"""Seed the knowledge container with KB articles + resolved tickets.

Usage: PYTHONPATH=src uv run python scripts/seed_kb.py [--create]
"""

import argparse
import json

import local_env

from triage import cosmos, retrieval
from triage.ai import OpenAIEmbedder


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--create", action="store_true", help="create database + knowledge/triage containers (local emulator only)"
    )
    args = parser.parse_args()
    local_env.load()

    embedder = OpenAIEmbedder()
    container = cosmos.ensure_kb_container(embedder.dimensions) if args.create else cosmos.kb_container()
    if args.create:
        cosmos.ensure_triage_container()

    docs: list[retrieval.Document] = []
    for path in sorted((local_env.ROOT / "kb" / "articles").glob("*.md")):
        docs += retrieval.chunk_markdown(path.stem, path.read_text())
    for line in (local_env.ROOT / "kb" / "tickets.jsonl").read_text().splitlines():
        if line.strip():
            docs.append(retrieval.ticket_document(json.loads(line)))

    count = retrieval.Retriever(container, embedder).index(docs)
    kb = sum(d.kind == "kb" for d in docs)
    print(f"Indexed {count} documents ({kb} KB chunks, {count - kb} tickets) with {embedder.model}")


if __name__ == "__main__":
    main()
