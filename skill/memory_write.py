#!/usr/bin/env python3
"""
memory_write.py - Store new entry to Chroma
Usage: memory_write.py <problem> [--solution <code>] [--logic <explanation>]
       [--type <entry_type>] [--project <name>] [--language <lang>]
       [--importance <0.0-1.0>]
"""

import re
import sys
import json
import argparse
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from chroma_client import (
    get_chroma_client, get_embedding_function, get_settings,
    expand_path, COLLECTIONS
)
from logger import get_logger

log = get_logger("memory_write")

MAX_CONTENT_LENGTH = 5000
BLOCKED_PATTERNS = [
    r'<script', r'javascript:', r'data:text/',
    r'on\w+\s*=', r'<iframe',
]


def validate_content(text: str, field_name: str = "content") -> str:
    """Validate and sanitize input content."""
    if not text or not text.strip():
        raise ValueError(f"{field_name} must not be empty")

    text = text.strip()

    if len(text) > MAX_CONTENT_LENGTH:
        raise ValueError(f"{field_name} exceeds max length ({MAX_CONTENT_LENGTH} chars)")

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            raise ValueError(f"{field_name} contains disallowed content")

    return text


def validate_importance(value: float) -> float:
    """Clamp importance to valid range."""
    return max(0.0, min(1.0, float(value)))


def memory_write(
    problem: str,
    solution: str = None,
    logic_solution: str = None,
    entry_type: str = "chat",
    project: str = "default",
    language: str = None,
    importance: float = 0.5
):
    """Store new entry to Chroma using shared client singleton."""

    # Validate inputs
    problem = validate_content(problem, "problem")
    if solution:
        solution = validate_content(solution, "solution")
    if logic_solution:
        logic_solution = validate_content(logic_solution, "logic_solution")
    importance = validate_importance(importance)

    settings = get_settings()
    chroma_config = settings.get("chroma", {})
    persist_dir = expand_path(chroma_config.get("persist_directory", "~/.memory/chroma"))

    client = get_chroma_client()
    ef = get_embedding_function()

    # Build text content
    content_parts = [f"Problem: {problem}"]
    if solution:
        content_parts.append(f"Solution: {solution}")
    if logic_solution:
        content_parts.append(f"Logic: {logic_solution}")
    content = "\n\n".join(content_parts)

    # Metadata
    metadata = {
        "project": project,
        "entry_type": entry_type,
        "use_count": 0,
        "last_used": datetime.now().isoformat(),
        "importance": importance,
        "language": language or "unknown"
    }

    # Determine collection by entry_type
    type_to_collection = {
        "solution": "tasks",
        "skill": "tasks",
        "fact": "important",
        "decision": "progress",
        "baseline": "core",
        "chat": "casual",
        "prompt": "prompts"
    }

    collection_name = type_to_collection.get(entry_type, "casual")

    try:
        collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef
        )

        entry_id = str(uuid.uuid4())
        collection.add(
            ids=[entry_id],
            documents=[content],
            metadatas=[metadata]
        )

        log.info(f"Stored entry {entry_id[:8]} in {collection_name}")
        return {"id": entry_id, "collection": collection_name, "status": "stored"}

    except Exception as e:
        log.error(f"Write failed: {e}")
        return {"error": str(e), "status": "failed"}


def main():
    parser = argparse.ArgumentParser(description="Write to semantic memory")
    parser.add_argument("problem", help="Problem or topic description")
    parser.add_argument("--solution", "-s", help="Solution or answer")
    parser.add_argument("--logic", "-l", help="Logic/explanation")
    parser.add_argument("--type", "-t", default="chat", help="Entry type")
    parser.add_argument("--project", "-p", default="default", help="Project name")
    parser.add_argument("--language", help="Programming language")
    parser.add_argument("--importance", "-i", type=float, default=0.5, help="Importance 0.0-1.0")

    args = parser.parse_args()

    result = memory_write(
        problem=args.problem,
        solution=args.solution,
        logic_solution=args.logic,
        entry_type=args.type,
        project=args.project,
        language=args.language,
        importance=args.importance
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
