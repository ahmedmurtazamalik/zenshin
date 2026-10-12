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


def normalize(text):
    return " ".join(text.split())


def validate_settings(data):
    targets, rules = data["targets"], data["rules"]
    if not isinstance(targets, list) or not isinstance(rules, list):
        raise ValueError("Targets and rules must be lists")
    for target in targets:
        if not isinstance(target["id"], str) or not target["id"].strip():
            raise ValueError("Select a chat with a valid ID")
        if not isinstance(target["name"], str):
            raise ValueError("Chat names must be text")
    requests = []
    for rule in rules:
        if not all(isinstance(rule[key], str) and rule[key].strip()
                   for key in ("request", "response")):
            raise ValueError("Each rule needs a complete request and response")
        requests.append(normalize(rule["request"]))
    if len(set(requests)) != len(requests):
        raise ValueError("Use only one response per exact request")
    return targets, rules


def preview_latest(thread, rules):
    turns = thread.get("turns", [])
    if not turns:
        return None
    turn = turns[-1]
    messages = [item for item in turn.get("items", [])
                if item["type"] == "agentMessage" and item.get("text")]
    if not messages:
        return None
    message = messages[-1]
    response = next((rule["response"] for rule in rules
                     if normalize(rule["request"]) == normalize(message["text"])), None)
    # A persisted message is not proof of a live pending approval.
    return {"thread_id": thread["id"], "turn_id": turn["id"], "item_id": message["id"],
            "text": message["text"], "response": response,
            "status": "Rule matched — preview only" if response else "No exact rule match"}


def poll(app):
    if not app["running"]:
        return
    if app["state"].get("mode") == "desktop":
        return poll_desktop(app)
    previews = []
    for target in app["state"]["targets"]:
        thread = rpc(app["connection"], "thread/read",
                     {"threadId": target["id"], "includeTurns": True})["thread"]
        preview = preview_latest(thread, app["state"]["rules"])
        if not preview:
            continue
        preview["name"] = target["name"]
        previews.append(preview)
        fingerprint = hashlib.sha256(json.dumps(preview, sort_keys=True).encode()).hexdigest()
        if fingerprint not in app["state"]["seen"]:
            app["state"]["seen"].append(fingerprint)
            app["state"]["activity"].append({"time": int(time.time()), **preview})
            app["state"]["activity"] = app["state"]["activity"][-100:]
            save_state(app["path"], app["state"])
    app["previews"] = previews


def questions(thread):
    requests = []
    for turn in thread.get("turns", []):
        for item in turn.get("items", []):
            prompts = item.get("questions") or []
            # The verified desktop form handles one question per request.
            if item["type"] == "agentMessage" and len(prompts) == 1:
                question = prompts[0]
                requests.append({"thread_id": thread["id"], "turn_id": turn["id"],
                                 "item_id": item["id"], "text": question["title"],
                                 "options": question.get("options") or []})
    return requests


