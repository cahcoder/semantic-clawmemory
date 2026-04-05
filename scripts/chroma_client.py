#!/usr/bin/env python3
"""
chroma_client.py - Shared ChromaDB client for semantic-clawmemory
Singleton pattern - model loaded once, reused.
Features: GPU auto-detect, ThreadPoolExecutor parallel search.
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("semantic-memory")

# Singleton cache
_client = None
_ef = None

# Collection definitions (shared across modules)
COLLECTIONS = ["critical", "core", "plan", "spec", "important", "tasks", "casual", "prompts", "progress"]

# Collection priority weights (boost applied during scoring)
COLLECTION_PRIORITY = {
    "critical": 0.30,
    "core": 0.25,
    "plan": 0.22,
    "spec": 0.20,
    "important": 0.15,
    "progress": 0.12,
    "tasks": 0.10,
    "prompts": 0.05,
    "casual": 0.00,
}

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    log.error("chromadb not installed. Run: pip install chromadb sentence-transformers")
    sys.exit(1)


def _detect_device():
    """Auto-detect best compute device: cuda if available, else cpu."""
    try:
        import torch
        if torch.cuda.is_available():
            log.info("GPU detected: %s", torch.cuda.get_device_name(0))
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def expand_path(path_str):
    """Expand ~ to home directory."""
    if path_str.startswith("~/"):
        return str(Path.home() / path_str[2:])
    return path_str


def get_settings():
    """Load settings from config/settings.yaml with sensible defaults."""
    config_dir = Path(__file__).parent.parent / "config"
    settings_file = config_dir / "settings.yaml"

    if settings_file.exists():
        try:
            import yaml
            with open(settings_file) as f:
                return yaml.safe_load(f)
        except Exception as e:
            log.warning("Failed to load settings.yaml: %s, using defaults", e)

    return {
        "chroma": {
            "persist_directory": "~/.memory/chroma",
            "embedding_model": "all-MiniLM-L6-v2",
            "dimensions": 384,
        }
    }


def reset_singletons():
    """Reset singleton state (useful for testing)."""
    global _client, _ef
    _client = None
    _ef = None


def get_chroma_client():
    """Get or create cached ChromaDB client with auto-detected device."""
    global _client, _ef

    if _client is not None:
        return _client

    settings = get_settings()
    chroma_config = settings.get("chroma", {})

    persist_dir = expand_path(chroma_config.get("persist_directory", "~/.memory/chroma"))
    model_name = chroma_config.get("embedding_model", "all-MiniLM-L6-v2")
    device = _detect_device()

    os.makedirs(persist_dir, exist_ok=True)

    log.info("Loading embedding model '%s' on %s", model_name, device)

    _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_name,
        device=device,
    )

    _client = chromadb.PersistentClient(path=persist_dir)
    return _client


def get_embedding_function():
    """Get cached embedding function."""
    global _ef
    if _ef is None:
        get_chroma_client()
    return _ef


def get_collection(name):
    """Get a collection with cached embedding function."""
    client = get_chroma_client()
    ef = get_embedding_function()
    return client.get_collection(name=name, embedding_function=ef)


def get_or_create_collection(name):
    """Get or create a collection with cached embedding function."""
    client = get_chroma_client()
    ef = get_embedding_function()
    return client.get_or_create_collection(name=name, embedding_function=ef)


def query_collection(name, query_texts, n_results=5, where=None, where_document=None):
    """Query a single collection."""
    collection = get_collection(name)
    return collection.query(
        query_texts=query_texts,
        n_results=n_results,
        where=where,
        where_document=where_document,
    )


def format_results(query_results):
    """Format Chroma query results for output."""
    results = []
    documents = query_results.get("documents", [[]])[0]
    metadatas = query_results.get("metadatas", [[]])[0]
    distances = query_results.get("distances", [[]])[0]

    for i, doc in enumerate(documents):
        meta = metadatas[i] if i < len(metadatas) else {}
        dist = distances[i] if i < len(distances) else 0.0

        results.append({
            "content": doc,
            "metadata": meta,
            "distance": dist,
            "similarity": 1 - dist if dist else 1.0,
        })

    return results


def get_all_collections(client=None, embed_fn=None):
    """Get all existing memory collections with their stats."""
    if client is None:
        client = get_chroma_client()
    if embed_fn is None:
        embed_fn = get_embedding_function()

    collections = {}
    for name in COLLECTIONS:
        try:
            col = client.get_collection(name=name, embedding_function=embed_fn)
            collections[name] = col
        except Exception:
            pass
    return collections


def get_timestamp():
    """Return current UTC timestamp as ISO string."""
    return datetime.utcnow().isoformat() + "Z"


def _search_single_collection(args):
    """Worker function for parallel collection search.
    Args: tuple of (col_name, query, limit, where, client, ef)
    Returns: list of result dicts
    """
    col_name, query, limit, where, client, ef = args
    results = []
    try:
        collection = client.get_collection(name=col_name, embedding_function=ef)
        query_results = collection.query(
            query_texts=[query],
            n_results=limit,
            where=where if where else None,
        )

        documents = query_results.get("documents", [[]])[0]
        metadatas = query_results.get("metadatas", [[]])[0]
        distances = query_results.get("distances", [[]])[0]

        for i, doc in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 0
            results.append({
                "collection": col_name,
                "content": doc,
                "metadata": meta,
                "distance": dist,
                "similarity": 1 - dist if dist else 1.0,
            })
    except Exception:
        pass  # Collection might not exist yet
    return results


def _score_result(entry, recency_weight=0.05):
    """Calculate weighted score for a search result.
    
    Factors:
    - similarity (base score)
    - collection priority
    - importance (normalized from 0.5 baseline)
    - recency boost (recent entries get slight boost)
    """
    similarity = entry.get("similarity", 0)
    collection = entry.get("collection", "casual")
    metadata = entry.get("metadata", {})
    
    # Collection priority boost
    col_boost = COLLECTION_PRIORITY.get(collection, 0)
    
    # Importance boost (centered at 0.5)
    importance = metadata.get("importance", 0.5)
    importance_boost = (importance - 0.5) * 0.2
    
    # Recency boost (entries accessed recently get slight boost)
    recency_boost = 0
    last_used = metadata.get("last_used", "")
    if last_used:
        try:
            from datetime import datetime
            age_days = (datetime.now() - datetime.fromisoformat(last_used)).days
            # Exponential decay: newer = higher boost
            recency_boost = max(0, recency_weight * (1 - age_days / 90))
        except Exception:
            pass
    
    total_score = similarity + col_boost + importance_boost + recency_boost
    return total_score


def search_memory(query, project=None, entry_type=None, limit=5, collection=None):
    """Search across collections with optimized scoring.
    
    Args:
        query: Search query text
        project: Filter by project name
        entry_type: Filter by entry type (solution/skill/fact/decision/baseline/chat/prompt)
        limit: Maximum results to return
        collection: If specified, search only this collection (string). Otherwise search all.
    
    Returns:
        List of results sorted by weighted score (similarity + priority + importance + recency)
    """
    client = get_chroma_client()
    ef = get_embedding_function()

    # Single collection: direct call (no ThreadPool overhead)
    if collection:
        single_result = _search_single_collection(
            (collection, query, limit, {
                **({"project": project} if project else {}),
                **({"entry_type": entry_type} if entry_type else {})
            }, client, ef)
        )
        # Score and sort
        for entry in single_result:
            entry["score"] = _score_result(entry)
        single_result.sort(key=lambda x: x.get("score", 0), reverse=True)
        return single_result[:limit]

    # Multiple collections: parallel search with ThreadPoolExecutor
    collections_to_query = list(COLLECTIONS)

    where = {}
    if project:
        where["project"] = project
    if entry_type:
        where["entry_type"] = entry_type

    # Build args for each collection
    worker_args = [
        (col_name, query, limit, where, client, ef)
        for col_name in collections_to_query
    ]

    all_results = []

    # Parallel search across collections
    with ThreadPoolExecutor(max_workers=min(len(collections_to_query), 4)) as executor:
        futures = {executor.submit(_search_single_collection, arg): arg[0] for arg in worker_args}
        for future in as_completed(futures):
            try:
                results = future.result()
                all_results.extend(results)
            except Exception:
                pass

    # Apply weighted scoring
    for entry in all_results:
        entry["score"] = _score_result(entry)

    # Sort by weighted score (highest first)
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_results[:limit]
