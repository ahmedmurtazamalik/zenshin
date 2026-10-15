"""Local Codex approval previews and scoped desktop question responses."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

import ai_decision


ROOT = Path(__file__).resolve().parent


def load_state(path):
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
    else:
        state = {"targets": [], "rules": [], "activity": [], "seen": []}
    state.setdefault("mode", "preview")
    state.setdefault("attempts", {})
    state.setdefault("decision_method", "exact")
    state.setdefault("instructions", "")
    state.setdefault("ai_decisions", {})
    state.setdefault("auto_password", False)
    state.setdefault("auto_terms", False)
    return state


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically so an interrupted save doesn't lose settings/history.
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
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


def pipe_ready(pipe):
    if os.name != "nt":
        return bool(select.select([pipe], [], [], 0.2)[0])
    # Windows select accepts sockets only. Peek without consuming pipe bytes.
    import ctypes
    import msvcrt
    available = ctypes.c_ulong()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel.PeekNamedPipe(ctypes.c_void_p(msvcrt.get_osfhandle(pipe.fileno())),
                               None, 0, None, ctypes.byref(available), None):
        error = ctypes.get_last_error()
        if error == 109:  # Broken pipe: let rpc read EOF and the stderr detail.
            return True
        raise ctypes.WinError(error)
    if not available.value:
        time.sleep(.02)
    return bool(available.value)


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
            if not pipe_ready(process.stdout):
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
        process = subprocess.Popen(ai_decision.cli_command() + ["app-server"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=errors,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, RuntimeError):
        errors.close()
        raise
    connection = {"process": process, "errors": errors, "next_id": 0, "buffer": b""}
    try:
        rpc(connection, "initialize", {"clientInfo": {
            "name": "codex_approval_helper", "title": "Zenshin",
            "version": "0.1.0"}})
        process.stdin.write(b'{"method":"initialized","params":{}}\n')
        process.stdin.flush()
        return connection
    except Exception:
        close_connection(connection)
        raise


def normalize(text):
    return " ".join(text.split())


def set_progress(app, stage, chat="", detail="", started=None):
    previous = app.get("progress", {})
    # Keep the AI timer visible while later polls recheck its pending request.
    if app.get("analysis") and stage in {"reading", "inspecting"}:
        return
    steps = previous.get("steps", [])
    if stage not in steps and stage in {"reading", "inspecting", "deciding", "sending", "confirming"}:
        steps = steps + [stage]
    if started is None:
        started = (previous["started"] if previous.get("stage") == stage
                   and previous.get("chat") == chat else time.monotonic())
    app["progress"] = {"stage": stage, "chat": chat, "detail": detail,
                       "started": started, "steps": steps}


def progress_snapshot(app):
    progress = app.get("progress", {})
    stage = progress.get("stage", "waiting" if app["running"] else "paused")
    if not app["running"] and stage != "error":
        stage = "paused"
    return {"running": app["running"], "stage": stage,
            "chat": progress.get("chat", ""), "detail": progress.get("detail", ""),
            "steps": progress.get("steps", []),
            "elapsed": max(0, time.monotonic() - progress.get("started", time.monotonic()))}


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
        set_progress(app, "deciding", request.get("name", ""), "Using a saved decision.")
        return {**request, **saved, "status": "AI — " + saved["decision"]}
    if not app.get("analysis"):
        started = time.monotonic()
        set_progress(app, "deciding", request.get("name", ""), "AI is reviewing the recent messages.", started)
        app["analysis"] = {**ai_decision.start(data), "key": key, "request": request, "started": started}
    return {**request, "response": None, "status": "AI analysis pending — no response sent"}


def poll(app):
    if not app["running"]:
        return
    if not app.get("analysis"):
        app.pop("progress", None)
    try:
        check_chats(app)
    except Exception as error:
        set_progress(app, "error", app.get("progress", {}).get("chat", ""), str(error))
        raise
    job = app.get("analysis")
    if job:
        set_progress(app, "deciding", job["request"].get("name", ""),
                     "AI is reviewing the recent messages.", job["started"])
    else:
        progress = app.get("progress", {})
        set_progress(app, "waiting", progress.get("chat", ""),
                     progress.get("detail", "") if progress.get("stage") == "done" else "Check complete.")


def check_chats(app):
    finish_analysis(app)
    if app["state"].get("mode") == "desktop":
        return poll_desktop(app)
    previews = []
    for target in app["state"]["targets"]:
        set_progress(app, "reading", target["name"])
        thread = rpc(app["connection"], "thread/read",
                     {"threadId": target["id"], "includeTurns": True})["thread"]
        set_progress(app, "inspecting", target["name"])
        if app["state"]["decision_method"] == "exact":
            set_progress(app, "deciding", target["name"], "Matching your saved rule.")
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
    if not app.get("analysis"):
        set_progress(app, "done", app.get("progress", {}).get("chat", ""), "Preview updated; nothing sent.")


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
    if os.name == "nt":
        import windows_ui
        return windows_ui.run(check_desktop, app, windows_ui)
    import linux_ui
    return check_desktop(app, linux_ui)


def check_desktop(app, ui):

    previews = []
    app["previews"] = previews
    selected = []
    for target in app["state"]["targets"]:
        set_progress(app, "reading", target["name"])
        thread = rpc(app["connection"], "thread/read", {
            "threadId": target["id"], "includeTurns": True})["thread"]
        if thread.get("name") != target["name"]:
            app["running"] = False
            raise RuntimeError("The selected chat was renamed; select and save it again")
        selected.append((target, thread))
    # Inspect Chrome before opening Codex, which can dismiss its native popup.
    if os.name == "nt" and (app["state"].get("auto_password") or app["state"].get("auto_terms")):
        for target, thread in selected:
            if check_browser_request(app, ui, target, thread):
                return
    for target, thread in selected:
        try:
            ui.open_chat(target["id"], target["name"], on_open=lambda: set_progress(
                app, "opening", target["name"], "Waiting for the selected chat to load in Codex."))
        except Exception:
            app["running"] = False
            raise
        set_progress(app, "inspecting", target["name"])
        requests = list(reversed(questions(thread)))
        for card in ui.approval_cards(target["name"]):
            turns = thread.get("turns", [])
            if not turns:
                continue
            fingerprint = hashlib.sha256(card["text"].encode()).hexdigest()
            requests.insert(0, {**card, "thread_id": thread["id"], "turn_id": turns[-1]["id"],
                                "item_id": turns[-1]["id"] + ":approval:" + fingerprint,
                                "approval": True})
        latest = preview_latest(thread, app["state"]["rules"])
        if latest:
            requests.append({**latest, "options": [], "conversation": True})
        for request in requests:
            try:
                if request.get("approval"):
                    is_pending = any(card["text"] == request["text"]
                                     for card in ui.approval_cards(target["name"]))
                elif request.get("conversation"):
                    is_pending = ui.conversation_pending(target["name"], request["text"])
                else:
                    is_pending = ui.pending(target["name"], request["text"])
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
                    set_progress(app, "deciding", target["name"], "Matching your saved rule.")
                    response = next((rule["response"] for rule in app["state"]["rules"]
                                     if normalize(rule["request"]) == normalize(current["text"])), None)
                responses.append(response)
            preview = {**request, "name": target["name"], "response": responses[0],
                       "status": "Pending — every question needs authorization"}
            if decision:
                preview.update(decision)
            if request.get("approval") and responses[0] != "Allow once":
                responses[0] = None
                preview["response"] = None
            previews.append(preview)
            if len(prompts) > 1:
                preview["answers"] = [{"question": prompt["title"], "response": response}
                                      for prompt, response in zip(prompts, responses)]
            if any(response is None for response in responses):
                preview["status"] = "Pending — every question needs authorization"
                if not app.get("analysis"):
                    set_progress(app, "done", target["name"], "Request left for you; no answer sent.")
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
                    set_progress(app, "sending", target["name"], response)
                    notify = lambda stage: set_progress(app, stage, target["name"], response)
                    if request.get("approval"):
                        ui.approve(target["name"], prompt["title"], response, on_progress=notify)
                    elif request.get("conversation"):
                        ui.reply(target["name"], prompt["title"], response, on_progress=notify)
                    elif index + 1 < len(prompts):
                        ui.answer(target["name"], prompt["title"], response, prompts[index + 1]["title"], on_progress=notify)
                    else:
                        ui.answer(target["name"], prompt["title"], response, on_progress=notify)
            except Exception as error:
                if request.get("conversation") and persisted_reply(
                        app["connection"], target["id"], request["turn_id"], responses[0]):
                    attempt.update(status="sent", reply_confirmed_by="app_server")
                    preview["status"] = "Response delivered"
                else:
                    attempt["status"] = "uncertain"
                    attempt["error"] = str(error)
                    app["running"] = False
                    preview["status"] = "Unconfirmed — paused; inspect the chat manually"
            else:
                attempt["status"] = "sent"
                preview["status"] = "Response delivered"
                set_progress(app, "done", target["name"], "Response delivered.")
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


def check_browser_request(app, ui, target, thread):
    latest = preview_latest(thread, [])
    if not latest or thread["turns"][-1].get("status") != "completed":
        return False
    text = latest["text"].casefold()
    if not re.search(r"\b(?:please|cannot|can['’]t|unable|manual(?:ly)?|need|must|waiting|enter|fill|accept|check|requires?)\b", text):
        return False
    password = app["state"].get("auto_password", False) and "password" in text
    terms = app["state"].get("auto_terms", False) and bool(re.search(r"\bterms\b|\bcheckbox", text))
    if not password and not terms:
        return False
    recent = analysis_input(thread, latest, "")["messages"]
    context = "\n".join(message["text"] for message in recent)
    # Browser navigation URLs often appear only in the last turn's tool calls.
    context += "\n" + "\n".join(json.dumps(item.get("arguments", {}))
                                 for item in thread["turns"][-1].get("items", [])
                                 if item["type"] == "mcpToolCall")
    if re.search(r"https?://", latest["text"]):
        context = latest["text"]
    origins = []
    for address in re.findall(r"https?://[^\s<>\"'\\]+", context):
        try:
            origin = ui.site_origin(address.rstrip(".,;:)]}"))
        except ValueError:
            continue
        if origin not in origins:
            origins.append(origin)
    for origin in origins:
        request = ui.chrome_signup_request(origin, password=password, terms=terms)
        if not request:
            continue
        fingerprint = hashlib.sha256(json.dumps([origin, request], sort_keys=True).encode()).hexdigest()
        key = thread["id"] + ":" + latest["item_id"] + ":browser:" + fingerprint
        if key in app["state"]["attempts"]:
            continue
        description = ("Select Chrome's suggested password" if request["kind"] == "password"
                       else "Accept site terms: " + request["label"])
        completed = ("selected Chrome's suggested password" if request["kind"] == "password"
                     else "checked the site's terms agreement checkbox")
        response = f"Zenshin {completed} on {origin}. Continue within the existing task authorization."
        attempt = {**latest, "name": target["name"], "text": description + " on " + origin,
                   "response": response, "time": int(time.time()), "status": "sending"}
        cancel_analysis(app)
        app["state"]["attempts"][key] = attempt
        save_state(app["path"], app["state"])
        try:
            set_progress(app, "reading", target["name"], "Waiting for Chrome to finish loading.")
            ui.prepare_chrome_site(origin, open_site=False)
            set_progress(app, "sending", target["name"], description)
            ui.perform_chrome_signup_request(origin, request)
            attempt["browser_completed"] = True
            save_state(app["path"], app["state"])
            ui.open_chat(target["id"], target["name"])
            try:
                ui.reply(target["name"], latest["text"], response)
            except Exception:
                # A Windows provider can report an event error after Send.
                # Confirm the exact new persisted reply; never send it again.
                if not persisted_reply(app["connection"], target["id"], latest["turn_id"], response):
                    raise
                attempt["reply_confirmed_by"] = "app_server"
        except Exception as error:
            attempt.update(status="uncertain", error=str(error))
            app["running"] = False
        else:
            attempt["status"] = "sent"
            set_progress(app, "done", target["name"], description + "; Codex notified.")
        app["state"]["activity"].append(dict(attempt))
        app["state"]["activity"] = app["state"]["activity"][-100:]
        app["previews"] = [dict(attempt)]
        save_state(app["path"], app["state"])
        if attempt["status"] == "uncertain":
            raise RuntimeError("Browser action or Codex continuation was not confirmed: " + attempt["error"])
        return True
    return False


def persisted_reply(connection, thread_id, turn_id, response):
    fresh = rpc(connection, "thread/read", {"threadId": thread_id, "includeTurns": True})["thread"]
    turns = fresh.get("turns", [])
    original = next((index for index, turn in enumerate(turns) if turn["id"] == turn_id), None)
    if original is None:
        return False
    # Codex's composer linkifies bare URLs and appends a newline on Send.
    def echo(text):
        return normalize(re.sub(r"\[(https?://[^\s\]]+)\]\(\1\)", r"\1", text.replace("\\\n", "\n")))
    return any(item["type"] == "userMessage" and echo("\n".join(
        part.get("text", "") for part in item.get("content", []))) == echo(response)
        for turn in turns[original + 1:] for item in turn.get("items", []))


def snapshot(app):
    return {"connected": app["connection"] is not None, "running": app["running"],
            "mode": app["state"].get("mode", "preview"),
            "targets": app["state"]["targets"], "rules": app["state"]["rules"],
            "decision_method": app["state"]["decision_method"],
            "instructions": app["state"]["instructions"],
            "chrome_password_supported": os.name == "nt",
            "auto_password": app["state"].get("auto_password", False),
            "auto_terms": app["state"].get("auto_terms", False),
            "activity": app["state"]["activity"], "previews": app["previews"],
            "unconfirmed": sum(attempt["status"] not in {"sent", "reviewed"}
                               for attempt in app["state"]["attempts"].values()),
            "progress": progress_snapshot(app),
            "error": app["error"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state", type=Path, default=ROOT / ".local" / "state.json")
    args = parser.parse_args()
    app = {"path": args.state, "state": load_state(args.state), "running": False,
           "connection": None, "previews": [], "error": ""}
    operations = Lock()

    class Handler(BaseHTTPRequestHandler):
        # Browsers may pre-open an idle socket; do not let it block all requests.
        timeout = 2

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
                with operations:
                    return self.reply(snapshot(app))
            if self.path == "/api/progress":
                return self.reply(progress_snapshot(app))
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/assets/space-grotesk.ttf": ("assets/space-grotesk.ttf", "font/ttf"),
                     "/assets/zenshin.svg": ("assets/zenshin.svg", "image/svg+xml")}
            if self.path not in files:
                return self.reply({"error": "Not found"}, 404)
            filename, content_type = files[self.path]
            body = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            # Only read-only progress can run alongside a desktop action.
            with operations:
                self.handle_operation()

        def handle_operation(self):
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
                if self.path in {"/api/chrome-password", "/api/chrome-prepare"}:
                    if os.name != "nt":
                        raise ValueError("Chrome password selection is available on Windows only")
                    if data.get("thread_id"):
                        raise ValueError("The automatic Chrome-preparation hook was retired; chat-bound calls are no longer supported")
                    import windows_ui
                    try:
                        def prepare():
                            result = windows_ui.prepare_chrome_site(data["site"])
                            if self.path == "/api/chrome-password":
                                result = windows_ui.accept_chrome_password(data["site"])
                            return result
                        result = windows_ui.run(prepare)
                    except (OSError, RuntimeError) as error:
                        return self.reply({"error": str(error)}, 503)
                    return self.reply(result)
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
                    browser = {key: data.get(key, False) for key in ("auto_password", "auto_terms")}
                    if any(type(value) is not bool for value in browser.values()):
                        raise ValueError("Browser automation toggles must be on or off")
                    if os.name != "nt" and any(browser.values()):
                        raise ValueError("Automatic Chrome actions are available on Windows only")
                    state = {**app["state"], "targets": targets, "rules": rules, "mode": mode,
                             "decision_method": method, "instructions": instructions, **browser}
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
                if self.path != "/api/poll":
                    app.pop("progress", None)
                    app["error"] = ""
                elif app["running"]:
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

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Zenshin: http://127.0.0.1:{args.port}", flush=True)
    print("Starts paused. Keep the control window open to monitor.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        with operations:
            cancel_analysis(app)
            close_connection(app["connection"])
            if os.name == "nt":
                import windows_ui
                windows_ui.shutdown()


if __name__ == "__main__":
    main()
