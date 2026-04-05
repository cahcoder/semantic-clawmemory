#!/usr/bin/env python3
"""
memory_write.py - Store new entry to Chroma with quality controls
Usage: memory_write.py <problem> [--solution <code>] [--logic <explanation>]
       [--type <entry_type>] [--project <name>] [--language <lang>]
       [--importance <0.0-1.0>]

Quality controls:
- Deduplication: checks if similar entry exists before storing
- Minimum length: problem must be 20+ chars
- Quality check: rejects test/junk content
- Near-duplicate merge: similar content updates existing entry
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
    expand_path, COLLECTIONS, search_memory
)
from logger import get_logger

log = get_logger("memory_write")

MAX_CONTENT_LENGTH = 5000
MIN_PROBLEM_LENGTH = 20  # Minimum chars for problem to be considered meaningful
MIN_SOLUTION_LENGTH = 10  # Minimum chars for solution
BLOCKED_PATTERNS = [
    r'<script', r'javascript:', r'data:text/',
    r'on\w+\s*=', r'<iframe',
]
# Patterns indicating low-quality/test content
LOW_QUALITY_PATTERNS = [
    r'^test\s*$', r'^test\s+', r'\btest\b.*\btest\b',
    r'^abc\s*$', r'^xyz\s*$', r'^asdf\s*$',
    r'^foo\s*$', r'^bar\s*$', r'^baz\s*$',
    r'^(qwerty|asdf|zxcv)\s*$',
    r'^[0-9\s]+$',  # Only numbers and spaces
]
# Similarity threshold for deduplication (65% = same as search threshold)
DUPLICATE_SIMILARITY_THRESHOLD = 0.70


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


def check_quality(problem: str, solution: str = None) -> tuple[bool, str]:
    """Check if content meets minimum quality standards.
    
    Returns: (is_quality, reason) tuple
    """
    # Check for low-quality patterns
    for pattern in LOW_QUALITY_PATTERNS:
        if re.match(pattern, problem, re.IGNORECASE):
            return False, f"problem appears to be test/junk content: '{problem[:20]}'"
    
    # Check minimum length
    if len(problem) < MIN_PROBLEM_LENGTH:
        return False, f"problem too short ({len(problem)} < {MIN_PROBLEM_LENGTH} chars)"
    
    # If solution provided, check its quality too
    if solution and len(solution) < MIN_SOLUTION_LENGTH:
        return False, f"solution too short ({len(solution)} < {MIN_SOLUTION_LENGTH} chars)"
    
    # Check for excessive repetition (hallucination indicator)
    words = problem.lower().split()
    if len(words) >= 5:
        unique_words = set(words)
        repetition_ratio = 1 - (len(unique_words) / len(words))
        if repetition_ratio > 0.7:
            return False, f"problem has excessive word repetition ({repetition_ratio:.0%})"
    
    return True, "ok"


def check_duplicate(content: str, collection: str, threshold: float = DUPLICATE_SIMILARITY_THRESHOLD) -> tuple[bool, dict]:
    """Check if content is too similar to existing entry.
    
    Returns: (is_duplicate, existing_entry) tuple
    """
    results = search_memory(
        query=content,
        limit=3,
        collection=collection
    )
    
    for entry in results:
        if entry.get('similarity', 0) >= threshold:
            return True, entry
    
    return False, None


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
    importance: float = 0.5,
    skip_duplicate_check: bool = False
):
    """Store new entry to Chroma with quality controls.
    
    Quality controls:
    - Validates content (length, blocked patterns)
    - Checks quality (no test/junk content)
    - Checks for duplicates before storing
    - Rejects if content is too similar to existing entry
    """

    # Validate inputs
    problem = validate_content(problem, "problem")
    if solution:
        solution = validate_content(solution, "solution")
    if logic_solution:
        logic_solution = validate_content(logic_solution, "logic_solution")
    importance = validate_importance(importance)

    # Build text content
    content_parts = [f"Problem: {problem}"]
    if solution:
        content_parts.append(f"Solution: {solution}")
    if logic_solution:
        content_parts.append(f"Logic: {logic_solution}")
    content = "\n\n".join(content_parts)

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

    # Quality check
    is_quality, reason = check_quality(problem, solution)
    if not is_quality:
        log.warning(f"Quality check failed: {reason}")
        return {"status": "rejected", "reason": reason}

    # Deduplication check (skip if explicitly requested)
    if not skip_duplicate_check:
        is_dup, existing = check_duplicate(content, collection_name)
        if is_dup:
            log.info(f"Duplicate detected (similarity={existing.get('similarity', 0):.2f}), updating existing entry")
            # Update existing entry instead of creating new
            return update_existing_entry(existing, problem, solution, logic_solution, language, importance)

    # Metadata
    metadata = {
        "project": project,
        "entry_type": entry_type,
        "use_count": 0,
        "last_used": datetime.now().isoformat(),
        "importance": importance,
        "language": language or "unknown"
    }

    client = get_chroma_client()
    ef = get_embedding_function()

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


def update_existing_entry(existing, problem, solution, logic_solution, language, importance):
    """Update an existing entry instead of creating duplicate."""
    try:
        client = get_chroma_client()
        ef = get_embedding_function()
        collection = client.get_collection(name=existing['collection'], embedding_function=ef)
        
        # Build updated content
        content_parts = [f"Problem: {problem}"]
        if solution:
            content_parts.append(f"Solution: {solution}")
        if logic_solution:
            content_parts.append(f"Logic: {logic_solution}")
        content = "\n\n".join(content_parts)
        
        # Update metadata
        metadata = existing.get('metadata', {})
        metadata['use_count'] = metadata.get('use_count', 0) + 1
        metadata['last_used'] = datetime.now().isoformat()
        metadata['importance'] = max(metadata.get('importance', 0.5), importance)
        if language:
            metadata['language'] = language
        
        collection.update(
            ids=[existing['id']],
            documents=[content],
            metadatas=[metadata]
        )
        
        log.info(f"Updated existing entry {existing['id'][:8]}")
        return {
            "id": existing['id'],
            "collection": existing['collection'],
            "status": "updated",
            "previous_similarity": existing.get('similarity', 0)
        }
    except Exception as e:
        log.error(f"Update failed: {e}")
        return {"error": str(e), "status": "update_failed"}


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
