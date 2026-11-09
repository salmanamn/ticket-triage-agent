"""Ad-hoc retrieval check.

Usage: PYTHONPATH=src uv run python scripts/search_kb.py "query" [--kind kb|ticket] [-k 5]
"""

import argparse

import local_env

from triage import cosmos
from triage.ai import OpenAIEmbedder
from triage.retrieval import Retriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--kind", choices=["kb", "ticket"])
    parser.add_argument("-k", type=int, default=5)
    args = parser.parse_args()
    local_env.load()

    hits = Retriever(cosmos.kb_container(), OpenAIEmbedder()).search(args.query, k=args.k, kind=args.kind)
    for h in hits:
        print(f"{h.score:.3f}  {h.kind:<6}  {h.source:<24}  {h.title}")


if __name__ == "__main__":
    main()
