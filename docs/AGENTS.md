# Universal Semantic Memory

Works with: Claude Code, Gemini CLI, OpenCode, Cursor, Codex, any AI CLI via AGENTS.md.

---

## Quick Start

```bash
# Clone anywhere
git clone git@github.com:cahcoder/agents-memory.git ~/agents-memory

# Add to shell profile (pick one)
echo 'export MEMORY_DIR="$HOME/.memory/chroma"' >> ~/.bashrc
echo 'export SKILL_DIR="$HOME/agents-memory/skill"' >> ~/.bashrc

# Reload
source ~/.bashrc
```

---

## Memory Pipeline

```
Task → PRE-LLM: search relevant context → Inject → AI → POST-LLM: store learnings → Response
```

### PRE-LLM (Before AI thinks)
```bash
python3 $SKILL_DIR/memory_search.py "<task>" --project <name> --limit 5
```

### POST-LLM (After AI responds)
```bash
python3 $SKILL_DIR/memory_write.py "<problem>" --solution "<solution>" --type solution --project <name>
```

---

## Essential Commands

```bash
# Search memory
python3 $SKILL_DIR/memory_search.py "<query>"

# Store learning
python3 $SKILL_DIR/memory_write.py "<problem>" --solution "<solution>"

# Bootstrap new project
python3 $SKILL_DIR/memory_bootstrap.py <project_name> --architecture "<description>"

# Stats & cleanup
python3 $SKILL_DIR/memory_gc.py --stats

# Intelligence
python3 $SKILL_DIR/scripts/intelligence.py patterns
python3 $SKILL_DIR/scripts/intelligence.py velocity
```

---

## Entry Types

| Type | Use For |
|------|---------|
| `solution` | Problem → solution pairs |
| `skill` | Reusable techniques |
| `fact` | Factual knowledge |
| `decision` | Architecture choices |
| `baseline` | Project starting knowledge |

---

## Collections

- `critical/` — Never delete
- `core/` — Core knowledge
- `tasks/` — Task solutions
- `casual/` — Conversations
- `prompts/` — Templates
- `progress/` — Tracking

---

## Troubleshooting

**Collection not found**: Run bootstrap first
```bash
python3 $SKILL_DIR/memory_bootstrap.py <project>
```

**Slow search**: Model caching after first load (~5s)

**Empty results**: Memory is empty — start using write to populate

---

_Works everywhere. Remembers everything._
