# agents-memory

> **Universal semantic memory layer for AI CLI tools. Remembers everything, forgets nothing.**

Semantic memory system that grows smarter over time. Prevents context overflow and AI "gibberish" through semantic vector search.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## The Problem

AI CLI tools share a fatal flaw: **they forget everything between sessions**.

- Context window fills up → AI starts "gibberish"
- Same problems solved repeatedly → no learning
- Decisions made in session A are lost in session B
- Project context disappears when chat history grows too large

## The Solution

```
┌─────────────────────────────────────────────────────────────┐
│  PRE-LLM                  POST-LLM                          │
│     ↓                        ↓                              │
│  Query memory ──────────→  Store learning                  │
│     ↓                        ↓                              │
│  Inject context ────────→  Update patterns                 │
│                                                             │
│         Continuous Learning Loop                            │
└─────────────────────────────────────────────────────────────┘
```

**Pre-LLM**: Before AI processes a task → query relevant memory → inject context  
**Post-LLM**: After AI responds → analyze for new learnings → store to vector DB

## Features

| Feature | Description |
|---------|-------------|
| **Semantic Search** | HNSW/ANN vector search — finds context in 300K+ entries at O(log n) |
| **Query Expansion** | Expands queries with synonyms for better recall (restart → restart, reboot, reload...) |
| **Collection Priority** | Results weighted by collection importance (critical > core > plan > spec) |
| **Retrieval Feedback** | Frequently retrieved entries get score boost (implicit positive signal) |
| **LRU Cache** | Caches search results (200 entries, 5 min TTL) |
| **Query Optimization** | Stopword removal + smart snippet extraction |
| **Write Quality Control** | Quality checks, dedup, min length on stored entries |
| **Domain Collections** | Separate critical, core, plan, spec, important, tasks, casual, prompts, progress |
| **Garbage Collection** | Auto dedup, decay, trash old entries |

## Tech Stack

```
Language     │ Python 3.x + Node.js CLI
Embedding   │ sentence-transformers / all-MiniLM-L6-v2 (384 dims)
Vector DB   │ Chroma (embedded DuckDB, no daemon)
ANN Search  │ HNSW (ef_search=200, m=48)
Similarity  │ Cosine similarity
```

## Installation

### Git Clone (Recommended)

```bash
# Clone
git clone git@github.com:cahcoder/agents-memory.git
cd agents-memory

# Install globally from local path
npm install -g .

# Initialize (installs daemon + hook)
agents-memory init
```

### npm (When Published)

```bash
npm install -g agents-memory
agents-memory init
```

---

## Setup (Required After Install)

### 1. Configure OpenClaw

Edit `~/.openclaw/openclaw.json` — add these entries:

```json
{
  "hooks": {
    "internal": {
      "entries": {
        "agents-memory": { "enabled": true }
      }
    }
  },
  "plugins": {
    "entries": {
      "agents-memory": { "enabled": true }
    }
  }
}
```

Then restart gateway:
```bash
nohup openclaw gateway restart > /dev/null 2>&1 &
```

### 2. Verify Hooks Loaded

```bash
openclaw hooks list
```

Should show `agents-memory` with events: `message:preprocessed`, `session:compact:after`

### 3. Test Memory Pipeline

Send a message to your bot — check logs:
```bash
tail -f /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep agents-memory
```

---

## Essential Commands

| Command | Description |
|---------|-------------|
| `agents-memory init` | Initialize setup (daemon + hook) |
| `agents-memory search <query>` | Search memory |
| `agents-memory write <problem> [solution]` | Store learning |
| `agents-memory batch-write --json '[...]'` | Store multiple learnings |
| `agents-memory set-project <name>` | Set project context |
| `agents-memory bootstrap <project>` | Init project memory |
| `agents-memory gc [--stats]` | Run garbage collection |
| `agents-memory uninstall` | Complete uninstall |

---

## Quick Start

```bash
# Search memory
agents-memory search "postgres restart"

# Store a learning
agents-memory write "container postgres crash" "docker restart {container_name}"

# Bootstrap new project
agents-memory bootstrap myproject --architecture "FastAPI + PostgreSQL"

# Run GC
agents-memory gc --stats
agents-memory gc --dedup
```

---

## How It Works

### 1. Pre-LLM Hook

```
User: "restart postgres container"
    ↓
Hook fires: message:preprocessed
    ↓
agents-memory searches Chroma
    ↓
→ Finds: "docker restart {container_name}"
    ↓
INJECT: Relevant context injected into AI prompt
    ↓
AI processes WITH context
```

### 2. Post-LLM Hook

```
AI responds successfully
    ↓
Session compaction occurs
    ↓
Hook fires: session:compact:after
    ↓
Stores new learnings to Chroma
    ↓
Updates use_count, importance
```

### 3. Retrieval Feedback Loop

```
Entry retrieved in search
    ↓
retrieval_count++
last_retrieved updated
    ↓
Frequent retrieval = useful = score boost in future
```

Score boost formula: `retrieval_boost = min(0.10, 0.01 * log1p(retrieval_count))`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  OpenClaw Gateway                                           │
│                                                             │
│  hooks/agents-memory/handler.js ← Managed hook             │
└─────────────────────────────────────────────────────────────┘
                              ↓ socket
┌─────────────────────────────────────────────────────────────┐
│  agents-memory-daemon (systemd service)                    │
│                                                             │
│  memory_daemon.py ← UNIX socket server                     │
│  chroma_client.py ← ChromaDB client                        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Chroma Vector DB (~/.memory/chroma/)                      │
│                                                             │
│  collections: critical, core, plan, spec, important,       │
│              tasks, casual, prompts, progress              │
└─────────────────────────────────────────────────────────────┘
```

---

## Collections

| Collection | TTL | Purpose |
|------------|-----|---------|
| critical | never | Critical, time-sensitive |
| core | 5 years | System laws, design decisions |
| plan | never | Project plans, roadmaps |
| spec | never | Project specifications |
| important | 2 years | Important but not critical |
| tasks | on-complete | Solutions, skills, todos |
| casual | 30 days | Chat, preferences |
| prompts | 90 days | User prompts history |
| progress | never | Resume tracker |

---

## Entry Schema

```json
{
  "id": "uuid-v4",
  "project": "project_name",
  "entry_type": "solution | skill | fact | decision | baseline | chat",
  "problem": "What problem does this solve?",
  "solution": "Generic template or answer",
  "language": "python | bash | sql | yaml | ...",
  "use_count": 0,
  "last_used": "ISO timestamp",
  "importance": 0.0-1.0,
  "timestamp": "ISO timestamp"
}
```

---

## Configuration

```yaml
# config/settings.yaml
chroma:
  persist_directory: "~/.memory/chroma"
  embedding_model: "all-MiniLM-L6-v2"
  dimensions: 384

collections:
  default_importance: 0.5
  priority:
    critical: 0.30
    core: 0.25
    plan: 0.22
    spec: 0.20
    important: 0.15
    progress: 0.12
    tasks: 0.10
    prompts: 0.05
    casual: 0.00

memory:
  search:
    max_query_length: 200
    cache_ttl_seconds: 30
    cache_max_entries: 100
    hnsw:
      ef_search: 200
      ef_construction: 200
      m: 48

gc:
  dedup_interval_days: 7
  archive_after_days: 90
  trash_retention_days: 30
```

---

## Cleanup / Reset

### Fresh reinstall (keep config, reset memory):

```bash
# Stop daemon
systemctl --user stop agents-memory-daemon

# Delete memory data
rm -rf ~/.memory/chroma/
rm -rf ~/.memory/agents-memory/

# Restart daemon (will reinitialize)
systemctl --user start agents-memory-daemon
```

### Complete uninstall:

```bash
# Via CLI
agents-memory uninstall

# Or manual:
# 1. systemctl --user stop agents-memory-daemon memory-gc.timer memory-trash.timer
# 2. rm -rf ~/.memory/chroma/ ~/.memory/agents-memory/
# 3. rm -rf ~/.openclaw/hooks/agents-memory/
# 4. Edit ~/.openclaw/openclaw.json — remove:
#    - hooks.internal.entries.agents-memory
#    - plugins.entries.agents-memory
# 5. npm rm -g agents-memory
```

---

## License

MIT License — See [LICENSE](LICENSE)

---

*"Grows the Longer It Runs"*
