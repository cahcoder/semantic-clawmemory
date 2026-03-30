#!/usr/bin/env python3
"""
memory_daemon.py - Persistent daemon for fast semantic memory
Usage: python3 memory_daemon.py [--daemon]
"""

import sys
import os
import json
import socket
import signal
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

PID_FILE = "/tmp/agents-memory-daemon.pid"
SOCKET_FILE = "/tmp/agents-memory-daemon.sock"

def cleanup():
    try:
        if os.path.exists(SOCKET_FILE):
            os.unlink(SOCKET_FILE)
    except:
        pass
    try:
        if os.path.exists(PID_FILE):
            os.unlink(PID_FILE)
    except:
        pass

def signal_handler(sig, frame):
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def daemonize():
    """Fork and detach."""
    pid = os.fork()
    if pid > 0:
        print(f"Daemon started with PID {pid}", file=sys.stderr)
        time.sleep(0.5)
        sys.exit(0)
    
    os.setsid()
    os.chdir("/")
    
    # Redirect stdio to /dev/null instead of closing (avoid print failures)
    devnull = os.open("/dev/null", os.O_RDWR)
    os.dup2(devnull, 0)  # stdin -> /dev/null
    os.dup2(devnull, 1)  # stdout -> /dev/null
    os.dup2(devnull, 2)  # stderr -> /dev/null
    if devnull > 2:
        os.close(devnull)
    
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

def load_model():
    """Load model once."""
    from chroma_client import get_chroma_client, get_embedding_function
    print("Loading embedding model...", file=sys.stderr)
    sys.stderr.flush()
    get_chroma_client()
    get_embedding_function()
    print("Model ready", file=sys.stderr)
    sys.stderr.flush()

def handle_search(args):
    from chroma_client import get_chroma_client, get_embedding_function
    
    client = get_chroma_client()
    ef = get_embedding_function()
    
    query = args.get("query", "")
    project = args.get("project")
    entry_type = args.get("type")
    limit = args.get("limit", 5)
    
    collections = ["critical", "core", "important", "tasks", "casual", "prompts", "progress"]
    all_results = []
    
    where = {}
    if project:
        where["project"] = project
    if entry_type:
        where["entry_type"] = entry_type
    
    for col_name in collections:
        try:
            collection = client.get_collection(name=col_name, embedding_function=ef)
            qr = collection.query(
                query_texts=[query],
                n_results=limit,
                where=where if where else None
            )
            
            for i, doc in enumerate(qr.get("documents", [[]])[0]):
                if not doc:
                    continue
                meta = qr.get("metadatas", [[]])[0][i] if qr.get("metadatas") else {}
                dist = qr.get("distances", [[]])[0][i] if qr.get("distances") else 0
                all_results.append({
                    "collection": col_name,
                    "content": doc,
                    "metadata": meta,
                    "distance": dist,
                    "similarity": 1 - dist if dist else 1.0
                })
        except Exception:
            pass
    
    all_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    return all_results[:limit]

def handle_write(args):
    from chroma_client import get_chroma_client, get_embedding_function
    
    client = get_chroma_client()
    ef = get_embedding_function()
    
    problem = args.get("problem", "")
    solution = args.get("solution", "")
    project = args.get("project", "default")
    entry_type = args.get("type", "solution")
    logic = args.get("logic")
    
    content = f"Problem: {problem}\n\nSolution: {solution}"
    if logic:
        content += f"\n\nLogic: {logic}"
    
    metadata = {
        "entry_type": entry_type,
        "project": project,
        "language": "unknown",
        "importance": 0.5,
        "use_count": 0
    }
    
    collection = client.get_collection(name="tasks", embedding_function=ef)
    collection.add(
        documents=[content],
        metadatas=[metadata],
        ids=[f"task_{project}_{os.urandom(4).hex()}"]
    )
    return {"added": True}

def handle_client(conn):
    try:
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            try:
                msg = json.loads(data.decode())
                break
            except json.JSONDecodeError:
                continue
        
        if not data:
            conn.close()
            return
        
        msg = json.loads(data.decode())
        cmd = msg.get("cmd")
        args = msg.get("args", {})
        result = {"ok": False, "error": None, "data": None}
        
        try:
            if cmd == "search":
                result = {"ok": True, "data": handle_search(args)}
            elif cmd == "write":
                result = {"ok": True, "data": handle_write(args)}
            elif cmd == "ping":
                result = {"ok": True, "data": "pong"}
            else:
                result = {"ok": False, "error": f"Unknown command: {cmd}"}
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        
        conn.sendall((json.dumps(result) + "\n").encode())
    except Exception as e:
        try:
            conn.sendall((json.dumps({"ok": False, "error": str(e)}) + "\n").encode())
        except:
            pass
    finally:
        conn.close()

def run_daemon():
    if os.path.exists(SOCKET_FILE):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(SOCKET_FILE)
            sock.sendall(json.dumps({"cmd": "ping"}).encode())
            resp = sock.recv(1024)
            if resp:
                print("Daemon already running", file=sys.stderr)
                return True
        except:
            pass
    
    cleanup()
    daemonize()
    
    load_model()
    
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(SOCKET_FILE)
    sock.listen(5)
    
    print(f"Daemon listening on {SOCKET_FILE}", file=sys.stderr)
    
    while True:
        try:
            conn, _ = sock.accept()
            handle_client(conn)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)

def run_client():
    if not os.path.exists(SOCKET_FILE):
        print("Daemon not running. Starting...", file=sys.stderr)
        run_daemon()
        time.sleep(2)
    
    for i in range(3):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(SOCKET_FILE)
            
            cmd = sys.argv[1] if len(sys.argv) > 1 else "ping"
            args = {}
            if len(sys.argv) > 2:
                args = json.loads(sys.argv[2])
            
            sock.sendall(json.dumps({"cmd": cmd, "args": args}).encode())
            resp = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                resp += chunk
                if b"\n" in resp:
                    break
            
            if resp:
                sys.stdout.write(resp.decode())
                sys.stdout.flush()
            sock.close()
            return
        except Exception as e:
            if i < 2:
                time.sleep(1)
                continue
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        run_daemon()
    else:
        run_client()
