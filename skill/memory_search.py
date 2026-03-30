#!/usr/bin/env python3
"""
memory_search.py - Query Chroma for relevant context
Uses cached chroma_client singleton for model reuse
Usage: memory_search.py <query> [--project <name>] [--type <entry_type>] [--limit <n>]
"""

import sys
import json
import argparse
from pathlib import Path

# Add scripts to path - use cached chroma_client
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from chroma_client import search_memory


def memory_search(query, project=None, entry_type=None, limit=5):
    """Convenience wrapper used by other skill modules (bootstrap, pre_llm).
    Delegates to the parallel search in chroma_client.
    """
    return search_memory(
        query=query,
        project=project,
        entry_type=entry_type,
        limit=limit,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query semantic memory")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--project", help="Filter by project")
    parser.add_argument("--type", help="Filter by entry type")
    parser.add_argument("-n", "--limit", type=int, default=5, help="Max results")

    args = parser.parse_args()

    results = memory_search(
        query=args.query,
        project=args.project,
        entry_type=args.type,
        limit=args.limit,
    )

    print(json.dumps(results, indent=2))
