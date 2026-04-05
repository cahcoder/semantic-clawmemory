# OpenClaw Integration Guide

Complete guide to integrating agents-memory with OpenClaw managed hook system.

---

## What Was Fixed (2026-04-05)

### Problem Summary
After npm install + agents-memory init, the memory pipeline didn't run automatically.

### Root Causes Fixed

| # | Issue | Fix |
|---|-------|-----|
| 1 | Hook installed to `~/.openclaw/hook-packs/` but OpenClaw loads from `~/.openclaw/hooks/` | Install to `~/.openclaw/hooks/agents-memory/` directly |
| 2 | `handler.js` used ESM syntax (`import`/`export`) but loader uses CommonJS | Rewrite to pure CommonJS with `module.exports` |
| 3 | HOOK.md metadata used JSON5 object format inside YAML — not parsed correctly | Keep metadata simple, event names in YAML list format |
| 4 | Event structure was unknown — used `event.hook` but actual keys are `event.type` + `event.action` | Hook name = `"type:action"` format (e.g., `"message:preprocessed"`) |
| 5 | `getLastUserMsg()` couldn't find messages — context structure different from assumed | Use `event.context` which contains `from`, `to`, `body`, etc. not `messages` array |
| 6 | Daemon RUNTIME_DIR hardcoded to `/tmp` — systemd service couldn't find PID file | Added `AGENTS_MEMORY_RUNTIME_DIR` env var support |
| 7 | install-seamless.js installed as "plugin" instead of "managed hook" | Rewrite to install to `~/.openclaw/hooks/` not `~/.openclaw/extensions/` |

### Files Changed

```
scripts/install-seamless.js   - Full rewrite for managed hook + Type=forking service
scripts/memory_daemon.py      - Added AGENTS_MEMORY_RUNTIME_DIR env var support
hook-packs/agents-memory/     - NEW: Proper hook-pack structure
  HOOK.md                     - CommonJS-compatible metadata
  handler.js                  - Pure CommonJS dispatcher
```

---

## Correct Integration (Step by Step)

### Prerequisites
- OpenClaw installed (`npm install -g openclaw`)
- Node.js 18+

### Step 1: Install agents-memory

```bash
npm install -g agents-memory
```

This runs postinstall which:
1. Installs Python dependencies (chromadb, sentence-transformers, etc.)
2. Runs `install-seamless.js`

### Step 2: Initialize (creates daemon + installs hook)

```bash
agents-memory init
```

Or manually:
```bash
node /path/to/agents-memory/scripts/install-seamless.js
```

### Step 3: Verify Hook Installation

```bash
openclaw hooks list
```

Expected output:
```
Hooks (2/5 ready)
...
✓ ready  🧠 agents-memory  Semantic memory integration...  openclaw-managed
```

### Step 4: Restart Gateway

```bash
nohup openclaw gateway restart > /dev/null 2>&1 &
sleep 5
```

### Step 5: Verify Hook Loads

```bash
journalctl --user -u openclaw-gateway.service -f | grep agents-memory
```

Expected on gateway start:
```
[agents-memory] Hook triggered, hook= message:preprocessed
```

### Step 6: Test Pipeline

Send any message to your bot. Expected log output:
```
[agents-memory] Hook triggered, hook= message:preprocessed
[agents-memory] context keys: from,to,body,... messages count: undefined
[agents-memory] msg found: <your message>
[agents-memory] Query: <your message>...
[agents-memory] Injected <N> chars
```

---

## Directory Structure

```
~/.openclaw/
├── hooks/                          # Managed hooks directory
│   └── agents-memory/
│       ├── HOOK.md                 # Hook manifest
│       └── handler.js              # CommonJS event dispatcher
├── openclaw.json                   # OpenClaw config
└── extensions/                     # Plugins (NOT used by agents-memory)

~/.memory/agents-memory/
├── daemon.sock                     # Unix socket (runtime)
└── daemon.pid                      # PID file (runtime)

~/.config/systemd/user/
└── agents-memory-daemon.service    # Systemd service (Type=forking)
```

---

## Event Structure (Critical)

OpenClaw internal hook event structure:

```javascript
{
  type: "message",           // Event type (e.g., "message", "session")
  action: "preprocessed",    // Event action
  sessionKey: "...",         // Session identifier
  context: {                 // Message context (NOT messages array!)
    from: "...",
    to: "...",
    body: "...",             // The actual message text
    bodyForAgent: "...",
    timestamp: "...",
    channelId: "...",
    conversationId: "...",
    messageId: "...",
    senderId: "...",
    senderName: "...",
    senderUsername: "...",
    provider: "...",
    surface: "...",
    // etc.
  },
  messages: [],              // Conversation history (may be empty)
  timestamp: Date
}
```

**Hook name format**: `"type:action"` (e.g., `"message:preprocessed"`)

---

## HOOK.md Format

```yaml
---
name: agents-memory
description: "Semantic memory integration - queries ChromaDB for relevant context"
metadata:
  {
    "openclaw": {
      "emoji": "🧠",
      "events": ["message:preprocessed", "session:compact:after"],
      "requires": { "bins": ["python3"] }
    }
  }
---

# agents-memory

Description of what this hook does.

## Events

- `message:preprocessed` - Query memory before LLM call
- `session:compact:after` - Store learnings after compaction
```

**Note**: The JSON5 object inside YAML is valid — OpenClaw parses it with `JSON5.parse()`.

---

## handler.js Template (CommonJS)

```javascript
/**
 * My Hook - CommonJS managed hook
 * Events: type:action1, type:action2
 */

const net = require("net");

const SOCKET = process.env.HOME + "/.memory/agents-memory/daemon.sock";

// Unix socket call to daemon
function daemonCall(cmd, args) {
  return new Promise((resolve, reject) => {
    const s = net.createConnection(SOCKET, () => {
      s.write(JSON.stringify({cmd, args}));
      s.end();
    });
    let data = "";
    s.on("data", c => data += c);
    s.on("end", () => { 
      try { 
        const r = JSON.parse(data); 
        r.ok ? resolve(r.data) : reject(new Error(r.error)) 
      } catch { reject(new Error("parse error")) } 
    });
    s.on("error", reject);
    s.setTimeout(5000, () => { s.destroy(); reject(new Error("timeout")) });
  });
}

// Get message from event.context.body
function getMessageBody(event) {
  const ctx = event && event.context;
  return ctx && ctx.body;
}

// Event handlers
async function onMessagePreprocessed(event) {
  const body = getMessageBody(event);
  if (!body || body.length < 3) return;
  
  try {
    const results = await daemonCall("search", {query: body, limit: 3});
    if (results && results.length) {
      const context = results.map(r => r.content.slice(0, 150)).join("\n");
      event.messages.push({role: "system", content: context});
    }
  } catch (e) {
    console.warn("[my-hook] Error:", e.message);
  }
}

// Dispatcher
async function handler(event) {
  const hook = event && event.type && event.action 
    ? (event.type + ":" + event.action) 
    : undefined;
  
  console.log("[my-hook] Hook triggered, hook=", hook);
  
  if (hook === "message:preprocessed") {
    return onMessagePreprocessed(event);
  }
}

module.exports = handler;
module.exports.default = handler;
```

---

## Systemd Service (Type=forking)

```ini
[Unit]
Description=Agents Memory Daemon
After=network.target

[Service]
Type=forking
PIDFile=/home/user/.memory/agents-memory/daemon.pid
ExecStartPre=/bin/mkdir -p /home/user/.memory/agents-memory
ExecStart=/usr/bin/python3 /path/to/memory_daemon.py --daemon
ExecStop=/bin/kill -TERM $MAINPID
Environment="AGENTS_MEMORY_RUNTIME_DIR=/home/user/.memory/agents-memory"
Environment="PYTHONPATH=/path/to/agents-memory/scripts"
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

**Critical**: `Type=forking` + `PIDFile` is required for systemd to track the daemon and auto-restart it properly. Without this, systemd loses track of the child process after fork.

---

## Troubleshooting

### Hook shows "⏸ disabled" in `openclaw hooks list`

The hook exists but is disabled. Check if it's in the right directory:
```bash
ls -la ~/.openclaw/hooks/agents-memory/
```

### Hook registered but never fires

1. Check log for trigger:
   ```bash
   journalctl --user -u openclaw-gateway.service -f | grep agents-memory
   ```

2. Verify hook is loaded at startup:
   ```
   [hooks] loaded X internal hook handlers
   ```

### "Failed to load hook: Unexpected token 'export'"

Your `handler.js` uses ESM syntax but OpenClaw loader uses CommonJS. Rewrite to use `module.exports` instead of `export default`.

### "Hook triggered, hook= undefined"

Your handler is checking `event.hook` but OpenClaw events use `event.type` and `event.action`. Use:
```javascript
const hook = event && event.type && event.action 
  ? (event.type + ":" + event.action) 
  : undefined;
```

### Daemon not responding to socket calls

1. Check if daemon is running:
   ```bash
   systemctl --user status agents-memory-daemon
   ```

2. Check socket exists:
   ```bash
   ls -la ~/.memory/agents-memory/daemon.sock
   ```

3. Test socket manually:
   ```bash
   python3 -c "
   import socket, json
   s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
   s.connect('/home/user/.memory/agents-memory/daemon.sock')
   s.send(json.dumps({'cmd':'ping'}).encode())
   print(s.recv(1024).decode())
   s.close()
   "
   ```

---

## Todo List (For Package Maintainer)

- [x] Fix handler.js to CommonJS (done 2026-04-05)
- [x] Fix install-seamless.js to install hook not plugin (done 2026-04-05)
- [x] Add AGENTS_MEMORY_RUNTIME_DIR env var to daemon (done 2026-04-05)
- [x] Add hook-packs/agents-memory/ to package files (done 2026-04-05)
- [x] Update README.md with correct integration steps (pending)
- [x] Push changes to git (done: commit b12390c)
- [ ] Publish to npm (needs `npm publish`)
- [ ] Test on clean machine (manual)
- [ ] Add integration test to CI (optional)

---

## Quick Reference

```bash
# Install
npm install -g agents-memory

# Initialize (after npm install)
node ~/.npm-global/lib/node_modules/agents-memory/scripts/install-seamless.js

# Or use the CLI if it supports init
agents-memory init

# Verify hook
openclaw hooks list

# Restart gateway
nohup openclaw gateway restart > /dev/null 2>&1 &

# Watch logs
journalctl --user -u openclaw-gateway.service -f | grep agents-memory

# Manual daemon control
systemctl --user start agents-memory-daemon
systemctl --user status agents-memory-daemon
```
