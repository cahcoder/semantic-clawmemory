#!/usr/bin/env python3
"""
memory_gc.py - Memory garbage collection and maintenance
Usage: memory_gc.py [--dedup] [--decay] [--archive] [--trash] [--stats]
                     [--all] [--batch-size N]

Maintenance tasks:
- dedup: Remove duplicate entries (batch-limited)
- decay: Lower importance of rarely used entries (batch-limited)
- trash: Permanently delete low-importance old entries (batch-limited)
- stats: Show collection statistics
"""

import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from chroma_client import (
    get_chroma_client, get_embedding_function, get_settings,
    expand_path, COLLECTIONS
)
from logger import get_logger

log = get_logger("memory_gc")

DEFAULT_BATCH_SIZE = 500


def gc_dedup(batch_size=DEFAULT_BATCH_SIZE):
    """Remove duplicate entries based on content similarity, in batches."""
    client = get_chroma_client()
    ef = get_embedding_function()

    removed = 0
    for col_name in COLLECTIONS:
        try:
            collection = client.get_collection(name=col_name, embedding_function=ef)
            all_data = collection.get()

            ids = all_data.get("ids", [])
            documents = all_data.get("documents", [])
            metadatas = all_data.get("metadatas", [])

            if not ids:
                continue

            seen = {}
            to_delete = []

            for i, doc in enumerate(documents):
                key = doc[:200].lower().strip()
                if key in seen:
                    existing_idx = seen[key]
                    existing_meta = metadatas[existing_idx] if existing_idx < len(metadatas) else {}
                    current_meta = metadatas[i] if i < len(metadatas) else {}

                    if current_meta.get("use_count", 0) > existing_meta.get("use_count", 0):
                        to_delete.append(ids[existing_idx])
                        seen[key] = i
                    else:
                        to_delete.append(ids[i])
                else:
                    seen[key] = i

            # Batch delete
            for batch_start in range(0, len(to_delete), batch_size):
                batch = to_delete[batch_start:batch_start + batch_size]
                collection.delete(ids=batch)
                removed += len(batch)

        except Exception as e:
            log.warning("gc_dedup error on %s: %s", col_name, e)

    log.info("Dedup complete: removed %d duplicates", removed)
    return {"dedup": {"removed": removed}}


def gc_decay(batch_size=DEFAULT_BATCH_SIZE):
    """Lower importance of rarely used entries over time, in batches."""
    client = get_chroma_client()
    ef = get_embedding_function()

    decayed = 0
    for col_name in COLLECTIONS:
        if col_name == "critical":
            continue

        try:
            collection = client.get_collection(name=col_name, embedding_function=ef)
            all_data = collection.get()

            ids = all_data.get("ids", [])
            metadatas = all_data.get("metadatas", [])

            if not ids:
                continue

            to_update_ids = []
            to_update_metas = []

            for i, meta in enumerate(metadatas):
                last_used_str = meta.get("last_used", "2020-01-01")
                try:
                    last_used = datetime.fromisoformat(last_used_str)
                except (ValueError, TypeError):
                    last_used = datetime(2020, 1, 1)

                days_since_use = (datetime.now() - last_used).days

                if days_since_use > 30:
                    current_importance = meta.get("importance", 0.5)
                    decay_factor = min(days_since_use / 90, 0.5)
                    new_importance = current_importance * (1 - decay_factor)

                    if new_importance < current_importance:
                        to_update_ids.append(ids[i])
                        to_update_metas.append({
                            **meta,
                            "importance": new_importance,
                            "decayed": True,
                        })
                        decayed += 1

            # Batch update
            for batch_start in range(0, len(to_update_ids), batch_size):
                batch_ids = to_update_ids[batch_start:batch_start + batch_size]
                batch_metas = to_update_metas[batch_start:batch_start + batch_size]
                collection.update(ids=batch_ids, metadatas=batch_metas)

        except Exception as e:
            log.warning("gc_decay error on %s: %s", col_name, e)

    log.info("Decay complete: decayed %d entries", decayed)
    return {"decay": {"decayed": decayed}}


def gc_trash(batch_size=DEFAULT_BATCH_SIZE):
    """Permanently delete entries with very low importance that haven't been used in 90+ days."""
    client = get_chroma_client()
    ef = get_embedding_function()

    settings = get_settings()
    gc_config = settings.get("gc", {})
    trash_retention_days = gc_config.get("trash_retention_days", 30)
    cutoff_date = datetime.now() - timedelta(days=trash_retention_days + 60)  # 60 extra grace

    deleted = 0
    for col_name in COLLECTIONS:
        if col_name == "critical":
            continue

        try:
            collection = client.get_collection(name=col_name, embedding_function=ef)
            all_data = collection.get()

            ids = all_data.get("ids", [])
            metadatas = all_data.get("metadatas", [])

            if not ids:
                continue

            to_delete = []

            for i, meta in enumerate(metadatas):
                importance = meta.get("importance", 0.5)
                if importance > 0.15:
                    continue

                last_used_str = meta.get("last_used", "")
                if not last_used_str:
                    continue

                try:
                    last_used = datetime.fromisoformat(last_used_str)
                    if last_used < cutoff_date:
                        to_delete.append(ids[i])
                except (ValueError, TypeError):
                    continue

            # Batch delete
            for batch_start in range(0, len(to_delete), batch_size):
                batch = to_delete[batch_start:batch_start + batch_size]
                collection.delete(ids=batch)
                deleted += len(batch)

        except Exception as e:
            log.warning("gc_trash error on %s: %s", col_name, e)

    log.info("Trash complete: deleted %d entries", deleted)
    return {"trash": {"deleted": deleted}}


def gc_archive(batch_size=DEFAULT_BATCH_SIZE):
    """Archive old entries by marking them as archived (lower importance, flagged)."""
    client = get_chroma_client()
    ef = get_embedding_function()

    settings = get_settings()
    gc_config = settings.get("gc", {})
    archive_after_days = gc_config.get("archive_after_days", 90)
    cutoff_date = datetime.now() - timedelta(days=archive_after_days)

    archived = 0
    for col_name in COLLECTIONS:
        if col_name == "critical":
            continue

        try:
            collection = client.get_collection(name=col_name, embedding_function=ef)
            all_data = collection.get()

            ids = all_data.get("ids", [])
            metadatas = all_data.get("metadatas", [])

            if not ids:
                continue

            to_update_ids = []
            to_update_metas = []

            for i, meta in enumerate(metadatas):
                if meta.get("archived"):
                    continue  # Already archived

                last_used_str = meta.get("last_used", "")
                if not last_used_str:
                    continue

                try:
                    last_used = datetime.fromisoformat(last_used_str)
                    if last_used < cutoff_date:
                        to_update_ids.append(ids[i])
                        to_update_metas.append({
                            **meta,
                            "importance": meta.get("importance", 0.5) * 0.5,
                            "archived": True,
                            "archived_at": datetime.now().isoformat(),
                        })
                        archived += 1
                except (ValueError, TypeError):
                    continue

            # Batch update
            for batch_start in range(0, len(to_update_ids), batch_size):
                batch_ids = to_update_ids[batch_start:batch_start + batch_size]
                batch_metas = to_update_metas[batch_start:batch_start + batch_size]
                collection.update(ids=batch_ids, metadatas=batch_metas)

        except Exception as e:
            log.warning("gc_archive error on %s: %s", col_name, e)

    log.info("Archive complete: archived %d entries", archived)
    return {"archive": {"archived": archived}}


def gc_stats():
    """Get memory statistics."""
    client = get_chroma_client()
    ef = get_embedding_function()

    stats = {}
    total = 0
    for col_name in COLLECTIONS:
        try:
            collection = client.get_collection(name=col_name, embedding_function=ef)
            count = collection.count()
            stats[col_name] = count
            total += count
        except Exception:
            stats[col_name] = 0

    stats["_total"] = total
    log.info("Stats: %d total entries across %d collections", total, len(COLLECTIONS))
    return {"stats": stats}


def main():
    parser = argparse.ArgumentParser(description="Memory garbage collection")
    parser.add_argument("--dedup", action="store_true", help="Remove duplicates")
    parser.add_argument("--decay", action="store_true", help="Decay rarely used entries")
    parser.add_argument("--trash", action="store_true", help="Clean trash (low importance + old)")
    parser.add_argument("--archive", action="store_true", help="Archive old entries")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--all", action="store_true", help="Run all gc tasks")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Batch size for bulk operations (default: {DEFAULT_BATCH_SIZE})")

    args = parser.parse_args()

    results = {}
    bs = args.batch_size

    if args.stats or args.all:
        results.update(gc_stats())

    if args.dedup or args.all:
        results.update(gc_dedup(batch_size=bs))

    if args.decay or args.all:
        results.update(gc_decay(batch_size=bs))

    if args.archive or args.all:
        results.update(gc_archive(batch_size=bs))

    if args.trash or args.all:
        results.update(gc_trash(batch_size=bs))

    if not results:
        results = gc_stats()

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
