#!/usr/bin/env python3
"""
chroma_client.py - Shared ChromaDB client for semantic-clawmemory
Singleton pattern - model loaded once, reused
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Singleton cache
_client = None
_ef = None

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    print("ERROR: chromadb not installed. Run: pip install chromadb sentence-transformers")
    sys.exit(1)

def expand_path(path_str):
    if path_str.startswith("~/"):
        return str(Path.home() / path_str[2:])
    return path_str

def get_settings():
    config_dir = Path(__file__).parent.parent / "config"
    settings_file = config_dir / "settings.yaml"
    
    if settings_file.exists():
        import yaml
        with open(settings_file) as f:
            return yaml.safe_load(f)
    
    return {
        "chroma": {
            "persist_directory": "~/.memory/chroma",
            "embedding_model": "all-MiniLM-L6-v2",
            "dimensions": 384
        }
    }

def get_chroma_client():
    """Get or create cached ChromaDB client."""
    global _client, _ef
    
    if _client is not None:
        return _client
    
    settings = get_settings()
    chroma_config = settings.get("chroma", {})
    
    persist_dir = expand_path(chroma_config.get("persist_directory", "~/.memory/chroma"))
    model_name = chroma_config.get("embedding_model", "all-MiniLM-L6-v2")
    
    # Create directory if not exists
    os.makedirs(persist_dir, exist_ok=True)
    
    # Load embedding function (cached)
    _ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_name,
        device="cpu"
    )
    
    _client = chromadb.PersistentClient(path=persist_dir)
    
    return _client

def get_embedding_function():
    """Get cached embedding function."""
    global _ef
    if _ef is None:
        get_chroma_client()  # This sets _ef
    return _ef

def get_collection(name):
    """Get a collection with cached ef."""
    client = get_chroma_client()
    ef = get_embedding_function()
    return client.get_collection(name=name, embedding_function=ef)

def query_collection(name, query_texts, n_results=5, where=None, where_document=None):
    """Query a collection."""
    collection = get_collection(name)
    return collection.query(
        query_texts=query_texts,
        n_results=n_results,
        where=where,
        where_document=where_document
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
            "similarity": 1 - dist if dist else 1.0
        })
    
    return results

# For backward compatibility
def search_memory(query, project=None, entry_type=None, limit=5):
    """Search across all collections."""
    settings = get_settings()
    persist_dir = Path(settings["chroma"]["persist_directory"]).expanduser()
    
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

