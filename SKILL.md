---
name: semantic-memory
description: Universal semantic memory layer for AI CLI tools. Prevents context overflow and AI "gibberish" through semantic search with Chroma/HNSW.
metadata:
  {
    "openclaw":
      {
        "requires": { "commands": ["python3"] },
        "install":
          [
            {
              "id": "pip",
              "kind": "python",
              "packages": ["chromadb", "sentence-transformers", "python-dateutil", "pyyaml"],
              "label": "Install Python dependencies (pip)",
            },
          ],
      },
  }
---

# Semantic Memory Skill for OpenClaw

Universal memory layer that prevents context overflow and AI "gibberish" through semantic search.

## Overview

```
User Input → PRE-LLM: Query Chroma → AI Process → POST-LLM: Store Learnings → Response
```

Memory is called at TWO points:
- **PRE-LLM**: Load relevant context from Chroma
- **POST-LLM**: Store new learnings to Chroma

## Commands

| Command | Description |
|---------|-------------|
| `memory_search` | Query Chroma for relevant context |
| `memory_write` | Store new entry to Chroma |
| `memory_bootstrap` | Write project baseline (when memory empty) |
| `memory_gc` | Garbage collection, dedup, cleanup |
| `memory_pre_llm` | PRE-LLM hook: query + inject context |
| `memory_post_llm` | POST-LLM hook: analyze + store learnings |

## Installation

```bash
openclaw plugin install semantic-memory
# or
cp -r skill/* ~/.openclaw/skills/semantic-memory/
```

## Collections (Domain-Separated)

- `critical/` - Critical info, never delete
- `core/` - Core project knowledge
- `important/` - Important but not critical
- `tasks/` - Task-specific solutions
- `casual/` - Casual conversations, preferences
- `prompts/` - Saved prompts, templates
- `progress/` - Progress tracking, decisions

## Entry Schema

```json
{
  "id": "uuid",
  "project": "project_name",
  "entry_type": "solution | skill | fact | decision | baseline | chat",
  "problem": "description (searchable)",
  "solution": "sample code or answer (generic template)",
  "logic_solution": "why/how it works",
  "language": "python | bash | sql | yaml | ...",
  "use_count": 0,
  "last_used": "timestamp",
  "importance": 0.0-1.0,
  "timestamp": "when stored"
}
```

## Project Structure

```
agents-memory/
├── SKILL.md           ← This file
├── skill/             ← OpenClaw skill directory
│   ├── memory_search.py
│   ├── memory_write.py
│   ├── memory_bootstrap.py
│   ├── memory_pre_llm.py
│   ├── memory_post_llm.py
│   └── memory_gc.py
├── scripts/           ← Core Python CLI
├── config/            ← Settings
└── docs/             ← Documentation
```

## Usage in OpenClaw

After installation, memory pipeline runs automatically via AGENTS.md enforcement:

```
Task arrives → memory_pre_llm → inject context → AI → memory_post_llm → response
```

## Configuration

Edit `config/settings.yaml`:

```yaml
chroma:
  persist_directory: "~/.memory/chroma"
  embedding_model: "all-MiniLM-L6-v2"
  dimensions: 384

collections:
  default_importance: 0.5
  auto_boost_threshold: 3

gc:
  dedup_interval_days: 7
  archive_after_days: 90
  trash_retention_days: 30
```

## Design Document

See `docs/memory-design-architecture.md` for full design discussion.
