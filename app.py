"""Local Codex approval previews and scoped desktop question responses."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


ROOT = Path(__file__).resolve().parent


def load_state(path):
    if path.exists():
        state = json.loads(path.read_text())
    else:
        state = {"targets": [], "rules": [], "activity": [], "seen": []}
    state.setdefault("mode", "preview")
    state.setdefault("attempts", {})
    return state


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically so an interrupted save doesn't lose settings/history.
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(state, file, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def close_connection(connection):
    if not connection:
        return
    process = connection["process"]
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    process.stdin.close()
    process.stdout.close()
    connection["errors"].close()


def rpc(connection, method, params):
    # This build intentionally cannot send turns, resume chats, or approvals.
    if method not in {"initialize", "thread/list", "thread/read"}:
        raise ValueError("Unsupported read-only operation")
    connection["next_id"] += 1
    request_id = connection["next_id"]
    process = connection["process"]
    process.stdin.write((json.dumps({"id": request_id, "method": method,
                                    "params": params}) + "\n").encode())
    process.stdin.flush()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if b"\n" not in connection["buffer"]:
            if not select.select([process.stdout], [], [], 0.2)[0]:
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                connection["errors"].seek(0)
                detail = connection["errors"].read().decode(errors="replace")[-1500:]
                raise RuntimeError("Codex App Server exited. " + detail.strip())
            connection["buffer"] += chunk
            continue
        line, connection["buffer"] = connection["buffer"].split(b"\n", 1)
        message = json.loads(line)
        if message.get("id") == request_id and "method" not in message:
            if "error" in message:
                raise RuntimeError(message["error"]["message"])
            return message["result"]
    raise RuntimeError("Codex App Server did not respond within 10 seconds")


def connect():
    errors = tempfile.TemporaryFile()
    try:
        process = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=errors)
    except OSError:
        errors.close()
        raise
    connection = {"process": process, "errors": errors, "next_id": 0, "buffer": b""}
    try:
        rpc(connection, "initialize", {"clientInfo": {
            "name": "codex_approval_helper", "title": "Codex Approval Helper",
            "version": "0.1.0"}})
        process.stdin.write(b'{"method":"initialized","params":{}}\n')
        process.stdin.flush()
        return connection
    except Exception:
        close_connection(connection)
        raise


