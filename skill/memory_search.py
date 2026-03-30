#!/usr/bin/env python3
"""
memory_search.py - Query Chroma for relevant context
Uses cached chroma_client for model reuse
Usage: memory_search.py <query> [--project <name>] [--type <entry_type>] [--limit <n>]
"""

import sys
import json
import argparse
from pathlib import Path

# Add scripts to path - use cached chroma_client
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

try:
    from chroma_client import get_chroma_client, get_embedding_function, query_collection, format_results
except ImportError as e:
    print(f"ERROR: Failed to import chroma_client: {e}")
    print("Run: agents-memory init")
    sys.exit(1)


def memory_search(query: str, project: str = None, entry_type: str = None, limit: int = 5):
    """Query Chroma for relevant context using cached client."""
    
    # Initialize client (uses cached model if already loaded)
    client = get_chroma_client()
    ef = get_embedding_function()
    
    collections_to_query = ["critical", "core", "important", "tasks", "casual", "prompts", "progress"]
    all_results = []
    
    where = {}
    if project:
        where["project"] = project
    if entry_type:
        where["entry_type"] = entry_type
    
    for col_name in collections_to_query:
        try:
            collection = client.get_collection(name=col_name, embedding_function=ef)
            query_results = collection.query(
                query_texts=[query],
                n_results=limit,
                where=where if where else None
            )
            
            for i, doc in enumerate(query_results.get("documents", [[]])[0]):
                meta = query_results.get("metadatas", [[]])[0][i] if query_results.get("metadatas") else {}
                dist = query_results.get("distances", [[]])[0][i] if query_results.get("distances") else 0
                all_results.append({
                    "collection": col_name,
                    "content": doc,
                    "metadata": meta,
                    "distance": dist,
                    "similarity": 1 - dist if dist else 1.0
                })
        except Exception:
            pass
    
    # Sort by similarity
    all_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    return all_results[:limit]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query semantic memory")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--project", help="Filter by project")
    parser.add_argument("--type", help="Filter by entry type")
    parser.add_argument("-n", "--limit", type=int, default=5, help="Max results")
    
    args = parser.parse_args()
    
    results = memory_search(args.query, project=args.project, entry_type=args.type, limit=args.limit)
    
    # Output as JSON
    print(json.dumps(results, indent=2))
