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

import ai_decision


ROOT = Path(__file__).resolve().parent


def load_state(path):
    if path.exists():
        state = json.loads(path.read_text())
    else:
        state = {"targets": [], "rules": [], "activity": [], "seen": []}
    state.setdefault("mode", "preview")
    state.setdefault("attempts", {})
    state.setdefault("decision_method", "exact")
    state.setdefault("instructions", "")
    state.setdefault("ai_decisions", {})
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


def analysis_input(thread, request, instructions):
    messages = []
    for turn in thread.get("turns", []):
        for item in turn.get("items", []):
            if item["type"] == "agentMessage" and item.get("text"):
                messages.append({"role": "assistant", "text": item["text"]})
            elif item["type"] == "userMessage":
                text = "\n".join(part.get("text", "[non-text content omitted]")
                                 for part in item.get("content", []))
                messages.append({"role": "user", "text": text})
    return {"standing_instructions": instructions, "messages": messages[-8:],
            "request": {key: request.get(key) for key in
                        ("thread_id", "turn_id", "item_id", "text", "options")}}


def cancel_analysis(app):
    job = app.pop("analysis", None)
    if job:
        ai_decision.cancel(job)


def finish_analysis(app):
    job = app.get("analysis")
    if not job:
        return
    try:
        decision = ai_decision.result(job)
    except RuntimeError as error:
        app.pop("analysis", None)
        app["running"] = False
        decision = {"decision": "needs_input", "response": None, "reason": str(error)}
        app["state"]["ai_decisions"][job["key"]] = decision
        save_state(app["path"], app["state"])
        raise
    if decision is not None:
        app.pop("analysis", None)
        app["state"]["ai_decisions"][job["key"]] = decision
        app["state"]["activity"].append({**job["request"], **decision,
                                        "status": "AI analysis — " + decision["decision"],
                                        "time": int(time.time())})
        app["state"]["activity"] = app["state"]["activity"][-100:]
        save_state(app["path"], app["state"])


def analyze_request(app, thread, request):
    data = analysis_input(thread, request, app["state"]["instructions"])
    key = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    saved = app["state"]["ai_decisions"].get(key)
    if saved:
        return {**request, **saved, "status": "AI — " + saved["decision"]}
    if not app.get("analysis"):
        app["analysis"] = {**ai_decision.start(data), "key": key, "request": request}
    return {**request, "response": None, "status": "AI analysis pending — no response sent"}


def poll(app):
    if not app["running"]:
        return
    finish_analysis(app)
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
        if app["state"]["decision_method"] == "ai":
            structured = next((item for item in questions(thread)
                               if item["item_id"] == preview["item_id"]), None)
            preview = analyze_request(app, thread, {**preview, **(structured or {})})
            previews.append(preview)
            continue
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
    for turn in thread.get("turns", [])[-1:]:
        for item in turn.get("items", []):
            prompts = item.get("questions") or []
            if item["type"] == "agentMessage" and prompts:
                question = prompts[0]
                requests.append({"thread_id": thread["id"], "turn_id": turn["id"],
                                 "item_id": item["id"], "text": question["title"],
                                 "options": question.get("options") or [],
                                 **({"questions": prompts} if len(prompts) > 1 else {})})
    return requests


def verify_desktop_targets(app):
    # Desktop documents expose a title, not a thread URL. Require that title to
    # identify exactly one persisted chat before binding it to a selected ID.
    threads = []
    cursor = None
    while True:
        result = rpc(app["connection"], "thread/list", {"limit": 100, "cursor": cursor})
        threads.extend(result["data"])
        cursor = result.get("nextCursor")
        if not cursor:
            break
    for target in app["state"]["targets"]:
        matches = [thread["id"] for thread in threads
                   if thread.get("name") == target["name"]]
        # Newly created desktop chats can be readable by ID before thread/list
        # includes them. Validate their identity directly as well.
        thread = rpc(app["connection"], "thread/read", {
            "threadId": target["id"], "includeTurns": False})["thread"]
        if thread.get("name") != target["name"] or any(identity != target["id"] for identity in matches):
            raise ValueError("Desktop mode needs a unique chat title; rename duplicate chats first")
        if any(attempt["thread_id"] == target["id"] and attempt["status"] not in {"sent", "reviewed"}
               for attempt in app["state"]["attempts"].values()):
            raise ValueError("This chat has an unconfirmed attempt; resolve its question manually")


def poll_desktop(app):
    import linux_ui

    previews = []
    app["previews"] = previews
    for target in app["state"]["targets"]:
        thread = rpc(app["connection"], "thread/read", {
            "threadId": target["id"], "includeTurns": True})["thread"]
        if thread.get("name") != target["name"]:
            app["running"] = False
            raise RuntimeError("The selected chat was renamed; select and save it again")
        requests = list(reversed(questions(thread)))
        latest = preview_latest(thread, app["state"]["rules"])
        if latest:
            requests.append({**latest, "options": [], "conversation": True})
        for request in requests:
            try:
                is_pending = (linux_ui.conversation_pending(target["name"], request["text"])
                              if request.get("conversation") else linux_ui.pending(target["name"], request["text"]))
            except Exception as error:
                app["running"] = False
                raise RuntimeError("Desktop access failed: " + str(error)) from error
            if not is_pending:
                continue
            responses = []
            decision = None
            prompts = request.get("questions") or [{"title": request["text"], "options": request["options"]}]
            for prompt in prompts:
                current = {**request, "text": prompt["title"], "options": prompt.get("options") or []}
                if app["state"]["decision_method"] == "ai":
                    decision = analyze_request(app, thread, {**current, "name": target["name"]})
                    response = decision["response"] if decision.get("decision") in {"approve", "continue"} else None
                else:
                    response = next((rule["response"] for rule in app["state"]["rules"]
                                     if normalize(rule["request"]) == normalize(current["text"])), None)
                responses.append(response)
            preview = {**request, "name": target["name"], "response": responses[0],
                       "status": "Pending — every question needs authorization"}
            if decision:
                preview.update(decision)
            previews.append(preview)
            if len(prompts) > 1:
                preview["answers"] = [{"question": prompt["title"], "response": response}
                                      for prompt, response in zip(prompts, responses)]
            if any(response is None for response in responses):
                preview["status"] = "Pending — every question needs authorization"
                continue
            key = request["thread_id"] + ":" + request["item_id"]
            if key in app["state"]["attempts"]:
                preview["status"] = "Already attempted — no second response"
                continue
            attempt = {**preview, "time": int(time.time()), "status": "sending"}
            # Commit before any UI action, including opening the answer form.
            app["state"]["attempts"][key] = attempt
            save_state(app["path"], app["state"])
            try:
                for index, (prompt, response) in enumerate(zip(prompts, responses)):
                    if request.get("conversation"):
                        linux_ui.reply(target["name"], prompt["title"], response)
                    elif index + 1 < len(prompts):
                        linux_ui.answer(target["name"], prompt["title"], response, prompts[index + 1]["title"])
                    else:
                        linux_ui.answer(target["name"], prompt["title"], response)
            except Exception as error:
                attempt["status"] = "uncertain"
                attempt["error"] = str(error)
                app["running"] = False
                preview["status"] = "Unconfirmed — paused; inspect the chat manually"
            else:
                attempt["status"] = "sent"
                preview["status"] = "Response delivered"
            app["state"]["activity"].append(dict(attempt))
            app["state"]["activity"] = app["state"]["activity"][-100:]
            save_state(app["path"], app["state"])
            if attempt["status"] == "uncertain":
                raise RuntimeError("Desktop delivery was not confirmed: " + attempt["error"])
            # One response per check lets a queued Pause take effect before the next.
            return
        latest = preview_latest(thread, app["state"]["rules"])
        if latest and not any(entry["thread_id"] == target["id"] for entry in previews):
            if app["state"]["decision_method"] == "ai":
                latest = analyze_request(app, thread, {**latest, "name": target["name"]})
            previews.append({**latest, "name": target["name"],
                             "status": latest["status"] + " — no live response control; no response sent"})


def snapshot(app):
    return {"connected": app["connection"] is not None, "running": app["running"],
            "mode": app["state"].get("mode", "preview"),
            "targets": app["state"]["targets"], "rules": app["state"]["rules"],
            "decision_method": app["state"]["decision_method"],
            "instructions": app["state"]["instructions"],
            "activity": app["state"]["activity"], "previews": app["previews"],
            "unconfirmed": sum(attempt["status"] not in {"sent", "reviewed"}
                               for attempt in app["state"]["attempts"].values()),
            "error": app["error"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state", type=Path, default=ROOT / ".local" / "state.json")
    args = parser.parse_args()
    app = {"path": args.state, "state": load_state(args.state), "running": False,
           "connection": None, "previews": [], "error": ""}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") in {
                f"127.0.0.1:{args.port}", f"localhost:{args.port}"}

        def do_GET(self):
            if not self.valid_host():
                return self.reply({"error": "Invalid host"}, 403)
            if self.path == "/api/state":
                return self.reply(snapshot(app))
            if self.path != "/":
                return self.reply({"error": "Not found"}, 404)
            body = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            origin = self.headers.get("Origin")
            if (not self.valid_host() or self.headers.get("Content-Type") != "application/json"
                    or origin not in {None, f"http://127.0.0.1:{args.port}",
                                      f"http://localhost:{args.port}"}):
                return self.reply({"error": "Use the local control window"}, 403)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1_000_000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(size))
                if self.path == "/api/connect":
                    app["running"] = False
                    cancel_analysis(app)
                    close_connection(app["connection"])
                    app["connection"] = None
                    app["connection"] = connect()
                elif self.path == "/api/threads":
                    if not app["connection"]:
                        raise ValueError("Connect to Codex first")
                    return self.reply(rpc(app["connection"], "thread/list", {
                        "limit": 50, "cursor": data.get("cursor"),
                        "sortKey": "updated_at"}))
                elif self.path == "/api/target":
                    if not app["connection"]:
                        raise ValueError("Connect to Codex first")
                    thread = rpc(app["connection"], "thread/read", {
                        "threadId": data["id"], "includeTurns": False})["thread"]
                    if not thread.get("name"):
                        raise ValueError("Give this chat a unique title in Codex first")
                    return self.reply({"id": thread["id"], "name": thread["name"]})
                elif self.path == "/api/settings":
                    targets, rules = validate_settings(data)
                    mode = data.get("mode", "preview")
                    if mode not in {"preview", "desktop"}:
                        raise ValueError("Choose preview or desktop mode")
                    method = data.get("decision_method", "exact")
                    instructions = data.get("instructions", "")
                    if method not in {"exact", "ai"} or not isinstance(instructions, str):
                        raise ValueError("Choose exact rules or AI with text instructions")
                    state = {**app["state"], "targets": targets, "rules": rules, "mode": mode,
                             "decision_method": method, "instructions": instructions}
                    save_state(app["path"], state)
                    cancel_analysis(app)
                    app["state"] = state
                    app["running"] = False
                    app["previews"] = []
                elif self.path == "/api/start":
                    if not app["connection"] or not app["state"]["targets"]:
                        raise ValueError("Connect and save at least one selected chat first")
                    if app["state"]["decision_method"] == "ai" and not app["state"]["instructions"].strip():
                        raise ValueError("Write your standing instructions before starting AI analysis")
                    if app["state"].get("mode") == "desktop":
                        verify_desktop_targets(app)
                    app["running"] = True
                elif self.path == "/api/pause":
                    app["running"] = False
                    cancel_analysis(app)
                elif self.path == "/api/review":
                    app["running"] = False
                    for attempt in app["state"]["attempts"].values():
                        if attempt["status"] not in {"sent", "reviewed"}:
                            attempt["status"] = "reviewed"
                    save_state(app["path"], app["state"])
                elif self.path == "/api/poll":
                    poll(app)
                else:
                    return self.reply({"error": "Not found"}, 404)
                app["error"] = ""
                self.reply(snapshot(app))
            except (ValueError, KeyError, TypeError) as error:
                self.reply({"error": str(error)}, 400)
            except (OSError, RuntimeError) as error:
                app["running"] = False
                cancel_analysis(app)
                close_connection(app["connection"])
                app["connection"] = None
                app["error"] = str(error)
                self.reply(snapshot(app), 503)

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Codex Approval Helper: http://127.0.0.1:{args.port}", flush=True)
    print("Starts paused. Keep the control window open to monitor.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        cancel_analysis(app)
        close_connection(app["connection"])


if __name__ == "__main__":
    main()
