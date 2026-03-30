#!/usr/bin/env python3
"""
intelligence.py - Self-improvement loop for semantic-clawmemory

Features:
- Pattern detection (3x same problem)
- Auto-importance boost
- Template generation
- Cross-project learning
"""

import re
import sys
import json
import logging
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from chroma_client import (
    get_chroma_client, get_embedding_function,
    get_all_collections, get_timestamp, COLLECTIONS
)
from logger import get_logger

log = get_logger("intelligence")

# Settings
SETTINGS = {
    "pattern_threshold": 3,
    "boost_amount": 0.15,
    "decay_rate": 0.05,
    "min_importance": 0.1,
    "max_importance": 1.0,
    "template_threshold": 0.7,
}


def detect_patterns(project=None, limit=100):
    """
    Detect patterns: same/similar problem solved multiple times.
    Returns entries that appear 3+ times with increasing use_count.
    """
    client = get_chroma_client()
    embed_fn = get_embedding_function()

    patterns = []

    for col_name in COLLECTIONS:  # FIX: COLLECTIONS is a list, not dict
        try:
            collection = client.get_collection(name=col_name, embedding_function=embed_fn)
        except Exception:
            continue

        try:
            # ChromaDB .get() doesn't take limit param, use .peek() + iterate
            results = collection.get()
        except Exception:
            continue

        if not results or not results.get("ids"):
            continue

        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])  # FIX: plural "metadatas"

        problem_groups = defaultdict(list)

        for i, entry_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) else {}

            if project and metadata.get("project") != project:
                continue

            use_count = metadata.get("use_count", 0)

            if use_count >= SETTINGS["pattern_threshold"]:
                problem = documents[i] if i < len(documents) else ""
                if problem:
                    normalized = normalize_text(problem)
                    problem_groups[normalized].append({
                        "id": entry_id,
                        "problem": problem,
                        "solution": documents[i] if i < len(documents) else "",
                        "use_count": use_count,
                        "importance": metadata.get("importance", 0.5),
                        "project": metadata.get("project", "unknown"),
                    })

        for normalized, entries in problem_groups.items():
            if len(entries) >= 1:
                patterns.append({
                    "problem": entries[0]["problem"],
                    "solutions": list(set(e["solution"] for e in entries)),
                    "use_count": max(e["use_count"] for e in entries),
                    "projects": list(set(e["project"] for e in entries)),
                    "avg_importance": sum(e["importance"] for e in entries) / len(entries),
                })

    log.info("Detected %d patterns", len(patterns))
    return patterns


def normalize_text(text):
    """Normalize text for pattern detection."""
    if not text:
        return ""
    text = text.lower().strip()
    text = " ".join(text.split())
    text = re.sub(r'\d+', 'N', text)
    text = re.sub(r'/[^\s]+', '/PATH', text)
    text = re.sub(r'@[^\s]+', '@USER', text)
    return text


def auto_boost_importance(entry_id, collection_name, boost_amount=None):
    """Boost importance of an entry."""
    if boost_amount is None:
        boost_amount = SETTINGS["boost_amount"]

    client = get_chroma_client()
    embed_fn = get_embedding_function()

    try:
        collection = client.get_collection(name=collection_name, embedding_function=embed_fn)
        entry = collection.get(ids=[entry_id])

        if not entry or not entry.get("ids"):
            return None

        metadatas = entry.get("metadatas", [])  # FIX: plural
        if not metadatas:
            return None

        current_importance = metadatas[0].get("importance", 0.5)
        new_importance = min(SETTINGS["max_importance"], current_importance + boost_amount)

        collection.update(
            ids=[entry_id],
            metadatas=[{
                **metadatas[0],
                "importance": new_importance,
                "last_boosted": get_timestamp(),
            }]
        )

        log.info("Boosted %s: %.2f -> %.2f", entry_id[:8], current_importance, new_importance)
        return new_importance
    except Exception as e:
        log.error("auto_boost failed: %s", e)
        return None


def decay_importance(days_old=30, min_use_count=0):
    """Apply importance decay to old, rarely used entries."""
    client = get_chroma_client()
    embed_fn = get_embedding_function()
    collections = get_all_collections(client, embed_fn)

    decayed_count = 0

    for col_name, collection in collections.items():
        try:
            if col_name == "critical":
                continue

            entries = collection.get()
            if not entries or not entries.get("ids"):
                continue

            ids = entries.get("ids", [])
            metadatas = entries.get("metadatas", [])  # FIX: plural

            for i, entry_id in enumerate(ids):
                metadata = metadatas[i] if i < len(metadatas) else {}

                use_count = metadata.get("use_count", 0)
                if use_count > min_use_count:
                    continue

                last_used_str = metadata.get("last_used", "")
                if not last_used_str:
                    continue

                try:
                    last_used = datetime.fromisoformat(last_used_str)
                    age_days = (datetime.now() - last_used).days

                    if age_days >= days_old:
                        current_importance = metadata.get("importance", 0.5)
                        decay_periods = age_days / 30
                        decay_amount = SETTINGS["decay_rate"] * decay_periods
                        new_importance = max(
                            SETTINGS["min_importance"],
                            current_importance - decay_amount,
                        )

                        if new_importance < current_importance:
                            collection.update(
                                ids=[entry_id],
                                metadatas=[{
                                    **metadata,
                                    "importance": new_importance,
                                    "last_decayed": get_timestamp(),
                                }]
                            )
                            decayed_count += 1
                except Exception:
                    continue
        except Exception:
            continue

    log.info("Decayed %d entries", decayed_count)
    return decayed_count


def generate_template(solution_text, language="unknown"):
    """Generate a generic template from a concrete solution."""
    if not solution_text:
        return ""

    template = solution_text

    replacements = [
        (r'\bpostgres\b', '{service_name}'),
        (r'\bmysql\b', '{database_name}'),
        (r'\bredis\b', '{cache_name}'),
        (r'/home/[^\s/]+', '{user_home}'),
        (r'/var/[^\s/]+', '{var_path}'),
        (r'/srv/[^\s/]+', '{srv_path}'),
        (r'/tmp/[^\s/]+', '{tmp_path}'),
        (r'\b\d+\.\d+\.\d+\.\d+\b', '{ip_address}'),
        (r'\b\d{4,}\b', '{port}'),
        (r'--name\s+[^\s]+', '--name {container_name}'),
    ]

    for pattern, replacement in replacements:
        template = re.sub(pattern, replacement, template, flags=re.IGNORECASE)

    template = re.sub(r'\b[A-Z]{2,}\b', '{CONSTANT}', template)
    template = re.sub(r'\b[a-z]+_[a-z]+_[a-z]+\b', '{snake_case_var}', template)

    return template


def suggest_reusable_skills(project=None, min_use_count=3):
    """Suggest entries that could be reusable skills."""
    client = get_chroma_client()
    embed_fn = get_embedding_function()
    collections = get_all_collections(client, embed_fn)

    suggestions = []

    for col_name, collection in collections.items():
        try:
            entries = collection.get()
        except Exception:
            continue

        if not entries or not entries.get("ids"):
            continue

        ids = entries.get("ids", [])
        documents = entries.get("documents", [])
        metadatas = entries.get("metadatas", [])  # FIX: plural

        for i, entry_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) else {}
            document = documents[i] if i < len(documents) else ""

            use_count = metadata.get("use_count", 0)
            entry_project = metadata.get("project", "unknown")
            entry_type = metadata.get("entry_type", "unknown")

            if use_count < min_use_count:
                continue
            if project and entry_project == project:
                continue
            if entry_type not in ["solution", "skill"]:
                continue

            template = generate_template(document)

            suggestions.append({
                "original": document[:100],
                "template": template if template != document else None,
                "use_count": use_count,
                "projects": [entry_project],
                "type": entry_type,
                "suggested_action": "Create skill" if template != document else "Mark as reusable",
            })

    suggestions.sort(key=lambda x: x["use_count"], reverse=True)
    return suggestions[:20]


def analyze_learning_velocity(days=7):
    """Analyze how fast knowledge is being accumulated."""
    client = get_chroma_client()
    embed_fn = get_embedding_function()
    collections = get_all_collections(client, embed_fn)

    cutoff = datetime.now() - timedelta(days=days)

    stats = {
        "period_days": days,
        "total_entries": 0,
        "by_collection": {},
        "by_type": defaultdict(int),
        "by_language": defaultdict(int),
        "avg_importance": 0,
        "projects": set(),
    }

    importance_sum = 0
    count = 0

    for col_name, collection in collections.items():
        try:
            entries = collection.get()
        except Exception:
            continue

        if not entries or not entries.get("ids"):
            continue

        ids = entries.get("ids", [])
        metadatas = entries.get("metadatas", [])  # FIX: plural

        col_count = 0

        for i, entry_id in enumerate(ids):
            metadata = metadatas[i] if i < len(metadatas) else {}

            timestamp_str = metadata.get("timestamp", "")
            if not timestamp_str:
                # Fall back to last_used
                timestamp_str = metadata.get("last_used", "")
            if not timestamp_str:
                continue

            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp < cutoff:
                    continue
            except Exception:
                continue

            col_count += 1
            count += 1
            importance_sum += metadata.get("importance", 0.5)

            stats["by_type"][metadata.get("entry_type", "unknown")] += 1
            stats["by_language"][metadata.get("language", "unknown")] += 1
            if metadata.get("project"):
                stats["projects"].add(metadata["project"])

        if col_count > 0:
            stats["by_collection"][col_name] = col_count
            stats["total_entries"] += col_count

    if count > 0:
        stats["avg_importance"] = importance_sum / count

    stats["projects"] = list(stats["projects"])
    stats["by_type"] = dict(stats["by_type"])
    stats["by_language"] = dict(stats["by_language"])

    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Intelligence module for semantic-clawmemory")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("patterns", help="Detect patterns (repeated solutions)")
    subparsers.add_parser("velocity", help="Analyze learning velocity")
    subparsers.add_parser("suggestions", help="Suggest reusable skills")

    boost_parser = subparsers.add_parser("boost", help="Boost entry importance")
    boost_parser.add_argument("entry_id", help="Entry ID")
    boost_parser.add_argument("--collection", default="tasks", help="Collection name")
    boost_parser.add_argument("--amount", type=float, help="Boost amount")

    decay_parser = subparsers.add_parser("decay", help="Apply importance decay")
    decay_parser.add_argument("--days", type=int, default=30, help="Entry age in days")

    args = parser.parse_args()

    if args.command == "patterns":
        patterns = detect_patterns()
        print(json.dumps(patterns, indent=2))
    elif args.command == "velocity":
        stats = analyze_learning_velocity()
        print(json.dumps(stats, indent=2))
    elif args.command == "suggestions":
        suggestions = suggest_reusable_skills()
        print(json.dumps(suggestions, indent=2))
    elif args.command == "boost":
        new_imp = auto_boost_importance(args.entry_id, args.collection, args.amount)
        print(f"New importance: {new_imp}")
    elif args.command == "decay":
        count = decay_importance(args.days)
        print(f"Decayed {count} entries")
    else:
        parser.print_help()
