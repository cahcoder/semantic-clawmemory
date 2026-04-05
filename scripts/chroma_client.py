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
        dist = distances[i] if i < len(distances) and distances[i] is not None else 0.0
        # Clamp distance to valid range [0, 2], handle edge cases
        dist = max(0.0, min(2.0, float(dist) if dist else 0.0))
        # Chroma cosine distance: 0 = identical, 2 = opposite
        # similarity = 1 - (dist / 2) normalizes to [0, 1]
        similarity = 1.0 - (dist / 2.0) if dist is not None else 0.0

        results.append({
            "content": doc,
            "metadata": meta,
            "distance": dist,
            "similarity": max(0.0, similarity),  # Never return negative similarity
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


# Query expansion synonyms (common technical terms)
# Maps terms to their synonyms - expanded at search time
QUERY_SYNONYMS = {
    # Restart/reboot
    "restart": ["restart", "reboot", "start again", "reload", "reset"],
    "crash": ["crash", "crashes", "crashed", "fails", "failed", "failure", "broken", "error", "segfault", "panic"],
    "install": ["install", "installation", "setup", "set up", "configure", "setup"],
    "uninstall": ["uninstall", "remove", "delete", "clean", "purge"],
    "update": ["update", "upgrade", "updating", "upgrading", "patch"],
    "fix": ["fix", "fixes", "fixed", "fixing", "repair", "patch", "hotfix"],
    "error": ["error", "errors", "errored", "exception", "fail", "failed", "failure"],
    "bug": ["bug", "bugs", "buggy", "issue", "defect", "problem"],
    "memory": ["memory", "mem", "ram", "heap", "usage"],
    "disk": ["disk", "storage", "space", "storage", "ssd", "hdd", "disk space"],
    "cpu": ["cpu", "processor", "core", "compute"],
    "network": ["network", "net", "internet", "connection", "connectivity"],
    "docker": ["docker", "container", "containerd", "podman", "containerization"],
    "postgres": ["postgres", "postgresql", "pg", "database", "db"],
    "npm": ["npm", "node", "nodejs", "package manager", "npx"],
    "python": ["python", "python3", "pip", "py"],
    "git": ["git", "github", "version control", "commit", "branch"],
    "systemd": ["systemd", "service", "services", "daemon", "systemctl", "unit"],
    "gateway": ["gateway", "openclaw", "gateway daemon", "gateway service"],
    "hook": ["hook", "hooks", "plugin", "plugins", "integration"],
    "config": ["config", "configuration", "settings", "configure", "cfg"],
    "permission": ["permission", "permissions", "permission denied", "access", "auth", "authorization", "unauthorized", "forbidden"],
    "timeout": ["timeout", "timed out", "connection timeout", "request timeout", "slow", "latency"],
    "cache": ["cache", "cached", "caching", "clear cache", "invalidate"],
    "token": ["token", "tokens", "api key", "apikey", "api_key", "authentication"],
    "pipeline": ["pipeline", "pipelines", "workflow", "processing"],
}


def expand_query(query: str) -> str:
    """Expand query with synonyms for better recall.
    
    Instead of searching just 'restart', also search for 'reboot', 'start again', etc.
    This improves recall without sacrificing accuracy.
    """
    if not query or len(query) < 3:
        return query
    
    # Tokenize query
    words = query.lower().split()
    expanded_words = set(words)
    
    for word in words:
        # Remove common punctuation
        clean_word = word.strip('.,!?;:()[]{}')
        
        # Check if word has synonyms
        for key, synonyms in QUERY_SYNONYMS.items():
            if clean_word in synonyms or clean_word == key:
                # Add all synonyms to expanded query
                expanded_words.update(synonyms)
                break  # Only match once per word group
    
    # Rebuild query with expanded words
    expanded_query = ' '.join(sorted(expanded_words))
    
    # If expansion didn't add anything, return original
    if len(expanded_words) == len(words):
        return query
    
    return expanded_query


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
            dist = distances[i] if i < len(distances) and distances[i] is not None else 0
            # Clamp distance to valid range [0, 2], handle edge cases
            dist = max(0.0, min(2.0, float(dist) if dist else 0.0))
            # Chroma cosine distance: 0 = identical, 2 = opposite
            # similarity = 1 - (dist / 2) normalizes to [0, 1]
            similarity = 1.0 - (dist / 2.0) if dist is not None else 0.0
            results.append({
                "collection": col_name,
                "content": doc,
                "metadata": meta,
                "distance": dist,
                "similarity": max(0.0, similarity),  # Never return negative similarity
            })
    except Exception:
        pass  # Collection might not exist yet
    return results


# Minimum similarity threshold — below this, results are discarded
# Prevents hallucinations from low-quality matches
# 0.65 = 65% similarity minimum (conservative)
MIN_SIMILARITY_THRESHOLD = 0.65

# Maximum boost from collection priority (caps how much priority can outweigh similarity)
MAX_COLLECTION_BOOST = 0.15

# Keyword match bonus: if query keywords appear in content, boost score
KEYWORD_MATCH_BONUS = 0.15

# Minimum keyword matches required (if similarity is below threshold, keyword match can still qualify)
MIN_KEYWORD_MATCHES = 1


def _has_keyword_match(query: str, content: str) -> tuple[bool, float]:
    """Check if query keywords appear in content.
    
    Returns: (has_match, match_ratio) where match_ratio is 0.0-1.0
    """
    if not query or not content:
        return False, 0.0
    
    # Extract keywords (3+ char words, excluding stopwords)
    stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                 'to', 'of', 'and', 'or', 'but', 'in', 'on', 'at', 'by', 'for',
                 'with', 'about', 'against', 'between', 'into', 'through', 'during',
                 'before', 'after', 'above', 'below', 'from', 'up', 'down', 'out',
                 'off', 'over', 'under', 'again', 'further', 'then', 'once',
                 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each',
                 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
                 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'can', 'will'}
    
    query_words = [w.lower() for w in query.split() if len(w) >= 3 and w.lower() not in stopwords]
    content_lower = content.lower()
    
    if not query_words:
        return True, 1.0  # No extractable keywords, assume match
    
    matches = sum(1 for w in query_words if w in content_lower)
    match_ratio = matches / len(query_words)
    
    return matches >= MIN_KEYWORD_MATCHES, match_ratio


def _score_result(entry, query="", recency_weight=0.05):
    """Calculate weighted score for a search result.
    
    Factors:
    - similarity (base score) — PRIMARY factor
    - keyword_match — cross-validation that query terms appear in content
    - collection priority — CAPPED to prevent low-sim results dominating
    - importance (normalized from 0.5 baseline)
    - recency boost (recent entries get slight boost)
    
    Safety: Results MUST have either:
    - similarity >= MIN_SIMILARITY_THRESHOLD, OR
    - keyword match (query terms appear in content)
    
    This dual-filter prevents hallucinations from pure vector similarity.
    """
    similarity = entry.get("similarity", 0)
    content = entry.get("content", "")
    collection = entry.get("collection", "casual")
    metadata = entry.get("metadata", {})
    
    # Cross-validation: check keyword match
    has_keyword_match, match_ratio = _has_keyword_match(query, content)
    
    # PRIMARY filter: must pass similarity threshold OR keyword match
    if similarity < MIN_SIMILARITY_THRESHOLD and not has_keyword_match:
        return -1.0  # Will be filtered out
    
    # Base score from similarity
    score = similarity
    
    # Keyword match bonus (applies even if similarity is low)
    if has_keyword_match:
        score += KEYWORD_MATCH_BONUS * match_ratio
    
    # Collection priority boost (CAPPED)
    col_boost = min(COLLECTION_PRIORITY.get(collection, 0), MAX_COLLECTION_BOOST)
    score += col_boost
    
    # Importance boost (centered at 0.5)
    importance = metadata.get("importance", 0.5)
    importance_boost = (importance - 0.5) * 0.2
    score += importance_boost
    
    # Recency boost
    recency_boost = 0
    last_used = metadata.get("last_used", "")
    if last_used:
        try:
            from datetime import datetime
            age_days = (datetime.now() - datetime.fromisoformat(last_used)).days
            recency_boost = max(0, recency_weight * (1 - age_days / 90))
        except Exception:
            pass
    score += recency_boost
    
    return score


def search_memory(query, project=None, entry_type=None, limit=5, collection=None, use_expansion=True):
    """Search across collections with optimized scoring and optional query expansion.
    
    Args:
        query: Search query text
        project: Filter by project name
        entry_type: Filter by entry type (solution/skill/fact/decision/baseline/chat/prompt)
        limit: Maximum results to return
        collection: If specified, search only this collection (string). Otherwise search all.
        use_expansion: If True, expand query with synonyms for better recall (default: True)
    
    Returns:
        List of results sorted by weighted score (similarity + priority + importance + recency)
    """
    client = get_chroma_client()
    ef = get_embedding_function()

    # Expand query with synonyms for better recall
    original_query = query
    if use_expansion:
        query = expand_query(query)
        if query != original_query:
            logging.getLogger("semantic-memory").debug(
                f"Query expanded: '{original_query}' -> '{query}'"
            )

    # Single collection: direct call (no ThreadPool overhead)
    if collection:
        single_result = _search_single_collection(
            (collection, query, limit, {
                **({"project": project} if project else {}),
                **({"entry_type": entry_type} if entry_type else {})
            }, client, ef)
        )
        # Score and sort (pass query for keyword cross-validation)
        for entry in single_result:
            entry["score"] = _score_result(entry, query=original_query)
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

    # Apply weighted scoring (pass ORIGINAL query for keyword cross-validation)
    for entry in all_results:
        entry["score"] = _score_result(entry, query=original_query)

    # Filter out negative scores (below similarity threshold AND no keyword match)
    all_results = [r for r in all_results if r.get("score", -1) >= 0]

    # Sort by weighted score (highest first)
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_results[:limit]
