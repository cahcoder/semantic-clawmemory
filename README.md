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
| **Domain Collections** | Separate critical, core, tasks, casual, prompts, progress |
| **Sample Templates** | Generic code patterns, not garbage copies |
| **Self-Improvement** | Detects repeated problems → suggests reusable skills |
| **Baseline Enforcement** | Never start a project with empty memory |
| **Universal** | Works via AGENTS.md + wrapper for any AI CLI |

## Tech Stack

```
Language     │ Python 3.x
Embedding   │ sentence-transformers / all-MiniLM-L6-v2 (384 dims)
Vector DB   │ Chroma (embedded DuckDB, no daemon)
ANN Search  │ HNSW (M=32-48, ef=200-300)
Similarity  │ Cosine similarity
```

## Installation

### npm (Recommended - Universal)

```bash
# Install globally
npm install -g agents-memory

# Verify
agents-memory --help

# Initialize (first time)
agents-memory init
```

The npm package auto-installs Python dependencies on first use.

### Python (Direct/Development)

```bash
# Clone
git clone git@github.com:cahcoder/agents-memory.git
cd agents-memory

# Install dependencies
pip install -r requirements.txt

# Or use the memory-wrapper script directly
./scripts/memory-wrapper --help
```

### OpenClaw Plugin

```bash
# Via npm
npm install -g agents-memory

# Or clone + link
git clone git@github.com:cahcoder/agents-memory.git
cd agents-memory
npm link
```

# Install dependencies
pip install -r requirements.txt

# Add to PATH
export PATH="$PWD/skill:$PATH"
```

### OpenClaw Plugin

```bash
openclaw plugin install agents-memory
```

## After Install (Required for AI CLI Tools)

After installing, you need to create an `AGENTS.md` file in your project directory. This tells AI CLI tools (Claude Code, Gemini CLI, OpenCode, etc.) to use semantic memory.

### For AI CLI Tools (Claude Code, Gemini CLI, OpenCode, Codex, Cursor, etc.)

**Create `AGENTS.md` in your project root:**

```bash
# In your project directory
agents-memory init-project
# OR manually:
touch AGENTS.md
```

**Copy this content into `AGENTS.md`:**

```markdown
# Semantic Memory

## Memory Setup
- MEMORY_DIR: ~/.memory/chroma
- SKILL_DIR: ~/.npm-global/lib/node_modules/agents-memory/skill

## PRE-LLM Hook (Before AI thinks)
Before starting a task, query relevant memory:
bash: agents-memory pre "{task description}"
When results found, inject them into context.

## POST-LLM Hook (After AI responds)
After successful response, store new learnings:
bash: agents-memory post "{problem solved}" "{solution}"
Only store generic patterns, not specific values.

## Essential Commands
- agents-memory search <query>  - Search memory
- agents-memory write <problem> <solution> - Store learning
- agents-memory bootstrap <project> - Init project memory
```

### For OpenClaw
Skill auto-installed to `~/.openclaw/workspace/skills/agents-memory/`. No AGENTS.md needed.

---

## Quick Start

```bash
# Install
openclaw plugin install semantic-memory

# Query memory (PRE-LLM hook)
memory_search "postgres restart pattern"

# Store learning (POST-LLM hook)
memory_write "container postgres crash" \
  --solution "docker restart {container}" \
  --type solution

# Bootstrap new project
memory_bootstrap myproject \
  --architecture "FastAPI + PostgreSQL + Redis" \
  --tech-stack "Python, Docker, K8s"

# Garbage collection
memory_gc --stats
memory_gc --dedup
```

## How It Works

### 1. Pre-LLM Hook

```
User: "restart postgres container"
    ↓
memory_search("postgres restart")
    ↓
→ Chroma query (semantic, not keyword)
→ Finds: "docker restart {container}"
    ↓
INJECT: "Remember: postgres restart pattern = docker restart {container}"
    ↓
AI processes WITH context
```

### 2. Post-LLM Hook

```
AI responds successfully
    ↓
Analyze: Did AI learn something new?
    ↓
If new pattern/solution found:
  → Store to Chroma with metadata
  → Update use_count
  → Boost importance if used 3+ times
```

### 3. Self-Improvement

```
Same problem solved 3x manually
    ↓
System detects: "this pattern appears often"
    ↓
Suggests: "Store as generic template?"
    ↓
AI writes: docker restart {container_name}
    ↓
Next time: instant recall, no manual solve needed
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  AI CLI Tools (OpenClaw, Claude Code, Gemini CLI, etc.)    │
│                                                             │
│  AGENTS.md ── enforces ──→ Memory Pipeline                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  agents-memory                                         │
│                                                             │
│  skill/                                                     │
│  ├── memory_search.py      ← Query Chroma                  │
│  ├── memory_write.py       ← Store entries                  │
│  ├── memory_pre_llm.py     ← Pre-LLM hook                 │
│  ├── memory_post_llm.py    ← Post-LLM hook                │
│  ├── memory_bootstrap.py    ← Project baseline             │
│  └── memory_gc.py          ← Dedup, decay, archive         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Chroma Vector DB                                            │
│  ~/.memory/chroma/                                          │
│                                                             │
│  collections/                                               │
│  ├── critical/    ← Never delete                           │
│  ├── core/        ← Project baseline                       │
│  ├── tasks/       ← Solutions, skills                     │
│  ├── casual/      ← Chat, preferences                      │
│  ├── prompts/     ← Templates                              │
│  └── progress/    ← Decisions, tracking                    │
└─────────────────────────────────────────────────────────────┘
```

## Entry Schema

```json
{
  "id": "uuid-v4",
  "project": "project_name",
  "entry_type": "solution | skill | fact | decision | baseline | chat",
  "problem": "What problem does this solve?",
  "solution": "Generic template or answer",
  "logic_solution": "Why/how it works",
  "language": "python | bash | sql | yaml | ...",
  "use_count": 0,
  "last_used": "ISO timestamp",
  "importance": 0.0-1.0,
  "timestamp": "ISO timestamp"
}
```

## Sample Code Rule

Store **generic templates**, NOT exact copies:

```
❌ BAD — garbage accumulation:
   docker exec -it postgres_prod_001 pg_ctl restart...
   docker exec -it postgres_backup_002 pg_ctl restart...
   → 100 variations = garbage

✅ GOOD — reusable pattern:
   docker exec -it {container_name} pg_ctl restart -D {data_dir}
   → 1 entry = reusable everywhere
```

## Universal Compatibility

```
OpenClaw    │ AGENTS.md hook (native)
Claude Code │ AGENTS.md hook
Gemini CLI  │ AGENTS.md hook
OpenCode    │ AGENTS.md hook
Codex       │ AGENTS.md hook
Copilot     │ AGENTS.md hook
```

For non-OpenClaw tools:

```bash
# ~/.bashrc
alias opencode='memory-wrapper opencode'
alias gemini='memory-wrapper gemini'
```

Wrapper intercepts, runs Pre/Post hooks, calls actual CLI.

## Configuration

```yaml
# config/settings.yaml
chroma:
  persist_directory: "~/.memory/chroma"
  embedding_model: "all-MiniLM-L6-v2"
  dimensions: 384

gc:
  dedup_interval_days: 7
  archive_after_days: 90
  trash_retention_days: 30

memory:
  max_preload_entries: 10
  min_learning_confidence: 0.3
```

## License

MIT License — See [LICENSE](LICENSE)

---

*"Grows the Longer It Runs"*
