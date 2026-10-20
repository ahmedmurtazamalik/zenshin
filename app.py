"""Local AI-authorized Codex replies and Chrome actions."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shlex
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

import ai_decision
import updates
import zenshin_mcp


ROOT = Path(__file__).resolve().parent
INSTALL_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT
DEFAULT_INSTRUCTIONS = ("Approve permission and continuation requests needed to complete my current task. "
                        "Tell Codex to proceed with its recommended option when a choice is needed. "
                        "Use Zenshin for enabled Chrome password and terms actions. "
                        "Do not invent missing facts or credentials.")


def codex_setup(port, register=False):
    frozen = getattr(sys, "frozen", False)
    executable = str(Path(sys.executable).with_name("Zenshin-bridge.exe")) if frozen else sys.executable
    arguments = [] if frozen else ["-B", str(ROOT / "zenshin_mcp.py")]
    if port != 8765:
        arguments += ["--port", str(port)]
    launcher = [executable, *arguments]
    command = ["codex", "mcp", "add", "zenshin", "--", *launcher]
    # Display a command that preserves spaces and quotes in installation paths.
    manual = ("& " + " ".join("'" + part.replace("'", "''") + "'" for part in command)
              if os.name == "nt" else shlex.join(command))
    result = {"command": manual, "registered": False, "conflict": False}
    try:
        cli = ai_decision.cli_command()

        def run(arguments):
            process = subprocess.run(cli + arguments, capture_output=True, text=True,
                                     encoding="utf-8", timeout=15,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if process.returncode:
                raise RuntimeError(process.stderr.strip()[-1000:] or "Codex command failed")
            return process.stdout

        def inspect():
            servers = json.loads(run(["mcp", "list", "--json"]))
            entry = next((server for server in servers if server["name"] == "zenshin"), None)
            if entry is None:
                return
            transport = entry.get("transport", {})
            result["registered"] = (entry.get("enabled", True)
                and os.path.normcase(transport.get("command", "")) == os.path.normcase(executable)
                and transport.get("args", []) == arguments)
            result["conflict"] = not result["registered"]

        inspect()
        if register and not result["registered"]:
            run(["mcp", "add", "zenshin", "--", *launcher])
            inspect()
            if not result["registered"]:
                raise RuntimeError("Registration could not be verified. Check the manual setup below.")
        if register and result["registered"]:
            zenshin_mcp.install_codex_guidance()
        result["message"] = ("Registered for this installation. Automatic Zenshin guidance is installed for new Codex chats. Reload MCP connections or restart Codex to refresh existing chats."
            if register and result["registered"] else "Registered for this installation. Connect again to install or refresh automatic guidance, then reload Codex's MCP connections."
            if result["registered"] else "An old or disabled Zenshin registration exists. Connect Zenshin tools to replace it."
            if result["conflict"] else "Not registered yet. Connect once to make the two tools available to Codex.")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        result["message"] = "Could not check or register Zenshin: " + str(error) + ". Use manual setup below."
    return result


def load_state(path):
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
    else:
        state = {"targets": [], "activity": []}
    for obsolete in ("rules", "mode", "decision_method", "seen"):
        state.pop(obsolete, None)
    state.setdefault("attempts", {})
    if not state.get("instructions", "").strip():
        state["instructions"] = DEFAULT_INSTRUCTIONS
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
    # Reading persisted chat history can take longer than a connection check.
    timeout = 60 if method == "thread/read" else 10
    pending = {"started": time.monotonic(), "timeout": timeout, "bytes": 0}
    connection["pending_read"] = pending if method == "thread/read" else None
    deadline = pending["started"] + timeout
    try:
        while time.monotonic() < deadline:
            if b"\n" not in connection["buffer"]:
                if not pipe_ready(process.stdout):
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    connection["errors"].seek(0)
                    detail = connection["errors"].read().decode(errors="replace")[-1500:]
                    raise RuntimeError("Codex App Server exited. " + detail.strip())
                pending["bytes"] += len(chunk)
                connection["buffer"] += chunk
                continue
            line, connection["buffer"] = connection["buffer"].split(b"\n", 1)
            message = json.loads(line)
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise RuntimeError(message["error"]["message"])
                return message["result"]
        raise RuntimeError(f"Codex App Server did not respond within {timeout} seconds ({method})")
    finally:
        connection["pending_read"] = None


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
            "version": updates.VERSION}})
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
    if not app["running"] and stage not in {"error", "updating"}:
        stage = "paused"
    pending = (app.get("connection") or {}).get("pending_read")
    read = ({"elapsed": max(0, time.monotonic() - pending["started"]),
             "timeout": pending["timeout"], "bytes": pending["bytes"]} if pending else None)
    return {"running": app["running"], "stage": stage, "read": read,
            "chat": progress.get("chat", ""), "detail": progress.get("detail", ""),
            "steps": progress.get("steps", []),
            "elapsed": max(0, time.monotonic() - progress.get("started", time.monotonic()))}


def validate_settings(data):
    targets, instructions = data["targets"], data.get("instructions", "")
    if not isinstance(targets, list):
        raise ValueError("Selected chats must be a list")
    for target in targets:
        if not isinstance(target["id"], str) or not target["id"].strip():
            raise ValueError("Select a chat with a valid ID")
        if not isinstance(target["name"], str):
            raise ValueError("Chat names must be text")
    if not isinstance(instructions, str):
        raise ValueError("Write your AI instructions as text")
    return targets, instructions


def latest_message(thread):
    turns = thread.get("turns", [])
    if not turns:
        return None
    turn = turns[-1]
    messages = [item for item in turn.get("items", [])
                if item["type"] == "agentMessage" and item.get("text")]
    if not messages:
        return None
    message = messages[-1]
    return {"thread_id": thread["id"], "turn_id": turn["id"], "item_id": message["id"],
            "text": message["text"], "options": []}


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
        if decision["decision"] in {"needs_input", "no_response"}:
            app["state"]["activity"].append({**job["request"], **decision,
                                            "status": "skipped", "time": int(time.time())})
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
    if app["state"]["targets"]:
        poll_desktop(app)


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
            raise ValueError("Selected chats need unique titles; rename duplicate chats first")


def poll_desktop(app):
    if os.name == "nt":
        import windows_ui
        return windows_ui.run(check_desktop, app, windows_ui)
    import linux_ui
    return check_desktop(app, linux_ui)


def check_desktop(app, ui):

    for target in app["state"]["targets"]:
        set_progress(app, "reading", target["name"])
        thread = rpc(app["connection"], "thread/read", {
            "threadId": target["id"], "includeTurns": True})["thread"]
        if thread.get("name") != target["name"]:
            app["running"] = False
            raise RuntimeError("The selected chat was renamed; select and save it again")
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
        latest = latest_message(thread)
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
            if request["thread_id"] + ":" + request["item_id"] in app["state"]["attempts"]:
                continue
            responses = []
            decision = None
            prompts = request.get("questions") or [{"title": request["text"], "options": request["options"]}]
            for prompt in prompts:
                current = {**request, "text": prompt["title"], "options": prompt.get("options") or []}
                decision = analyze_request(app, thread, {**current, "name": target["name"]})
                response = decision["response"] if decision.get("decision") in {"approve", "continue"} else None
                responses.append(response)
            if request.get("approval") and responses[0] != "Allow once":
                responses[0] = None
            if any(response is None for response in responses):
                continue
            key = request["thread_id"] + ":" + request["item_id"]
            response_record = {**request, "name": target["name"], "response": responses[0]}
            if len(prompts) > 1:
                response_record["answers"] = [{"question": prompt["title"], "response": response}
                                      for prompt, response in zip(prompts, responses)]
            attempt = {**response_record, "time": int(time.time()), "status": "sending"}
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
                confirmed = False
                if request.get("conversation"):
                    try:
                        confirmed = persisted_reply(app["connection"], target["id"], request["turn_id"], responses[0])
                    except (OSError, RuntimeError):
                        pass
                if confirmed:
                    attempt.update(status="sent", reply_confirmed_by="app_server")
                else:
                    attempt.update(status="uncertain", error=str(error))
                    set_progress(app, "done", target["name"], "Delivery was not confirmed; duplicate send skipped.")
            else:
                attempt["status"] = "sent"
                set_progress(app, "done", target["name"], "Response delivered.")
            app["state"]["activity"].append(dict(attempt))
            app["state"]["activity"] = app["state"]["activity"][-100:]
            save_state(app["path"], app["state"])
            # One response per check lets a queued Pause take effect before the next.
            return


def browser_action(app, data):
    if os.name != "nt":
        raise ValueError("Individual Chrome actions currently require Windows; Codex approvals and forms also support Linux")
    action = data.get("action")
    if action not in {"password", "terms"}:
        raise ValueError("Choose one password or terms action")
    if not app["running"] or not app["state"].get("auto_" + action):
        raise ValueError("Enable this Chrome action, save, and Start monitoring in Zenshin first")
    site, request_id, label = data.get("site"), data.get("request_id"), data.get("label", "")
    if not all(isinstance(value, str) and value.strip() for value in (site, request_id)):
        raise ValueError("A site URL and stable request_id are required")
    if not isinstance(label, str) or (action == "terms" and not label.strip()):
        raise ValueError("Terms actions require the exact checkbox label")
    import windows_ui
    origin = windows_ui.site_origin(site)
    key = "browser:" + request_id
    identity = {"action": action, "site": site, "label": label}
    prior = app["state"]["attempts"].get(key)
    if prior:
        if prior["request"] != identity:
            raise ValueError("This request_id belongs to a different browser action")
        if prior["status"] == "sent":
            return {**prior["result"], "replayed": True}
        raise RuntimeError("This action was already attempted without confirmation; duplicate action skipped")
    description = "Select Chrome's suggested password" if action == "password" else "Check terms: " + label
    attempt = {"kind": "browser_action", "thread_id": "", "name": "Chrome",
               "request": identity, "text": description + " on " + origin,
               "time": int(time.time()), "status": "sending"}
    app["state"]["attempts"][key] = attempt
    save_state(app["path"], app["state"])
    try:
        def perform():
            windows_ui.prepare_chrome_site(site, open_site=False)
            if action == "password":
                windows_ui.open_chrome_password_suggestion(site)
            request = windows_ui.chrome_signup_request(origin, password=action == "password",
                                                       terms=action == "terms", label=label or None)
            if not request:
                raise RuntimeError("The requested native password suggestion or unchecked terms box is not available")
            windows_ui.perform_chrome_signup_request(origin, request)
        windows_ui.run(perform)
        result = {"request_id": request_id, "action": action, "site": origin, "confirmed": True,
                  "message": description + " confirmed. Continue the current task using your normal tools."}
        attempt.update(status="sent", result=result)
    except Exception as error:
        attempt.update(status="uncertain", error=str(error))
        raise RuntimeError("Chrome action was not confirmed; do not retry. " + str(error)) from error
    finally:
        app["state"]["activity"].append(dict(attempt))
        app["state"]["activity"] = app["state"]["activity"][-100:]
        save_state(app["path"], app["state"])
    return result


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
            "version": updates.VERSION,
            "updates_supported": os.name == "nt" and getattr(sys, "frozen", False),
            "targets": app["state"]["targets"],
            "instructions": app["state"]["instructions"],
            "chrome_password_supported": os.name == "nt",
            "auto_password": app["state"].get("auto_password", False),
            "auto_terms": app["state"].get("auto_terms", False),
            "activity": app["state"]["activity"],
            "progress": progress_snapshot(app),
            "error": app["error"]}


def check_codex_connection(app):
    if not app["connection"]:
        return {"connected": False, "message": "Chat connection: not connected. Open Chats and choose Load Codex chats."}
    try:
        rpc(app["connection"], "thread/list", {"limit": 1})
        return {"connected": True, "message": "Chat connection: connected. Codex responded successfully."}
    except (OSError, RuntimeError) as error:
        app["running"] = False
        cancel_analysis(app)
        close_connection(app["connection"])
        app["connection"] = None
        return {"connected": False, "message": "Chat connection: disconnected. " + str(error) + ". Load Codex chats to reconnect."}


def start_monitoring(app):
    state = app["state"]
    if state["targets"]:
        if not app["connection"]:
            raise ValueError("Load Codex chats to reconnect before starting")
        if not state["instructions"].strip():
            raise ValueError("Write your standing instructions before starting")
        verify_desktop_targets(app)
    elif not (state.get("auto_password") or state.get("auto_terms")):
        raise ValueError("Select a chat or enable a Chrome action first")
    app["running"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state", type=Path, default=INSTALL_ROOT / ".local" / "state.json")
    parser.add_argument("--repair-registration", action="store_true", help="Replace old Zenshin tool registration after installation")
    parser.add_argument("--mcp", action="store_true", help="Run the Codex tool bridge over stdio")
    parser.add_argument("--no-browser", action="store_true", help="Run the local server without the desktop window")
    args = parser.parse_args()
    if args.mcp:
        import zenshin_mcp
        return zenshin_mcp.serve(args.port)
    app = {"path": args.state, "state": load_state(args.state), "running": False,
           "connection": None, "error": ""}
    operations = Lock()
    window = None
    repair_registration = args.repair_registration

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
            nonlocal repair_registration
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
                if self.path == "/api/codex-setup":
                    result = codex_setup(args.port, register=repair_registration or data.get("register") is True)
                    if result["registered"]:
                        repair_registration = False
                    return self.reply(result)
                if self.path == "/api/check-update":
                    try:
                        return self.reply(updates.latest_release())
                    except (OSError, RuntimeError, ValueError, KeyError) as error:
                        return self.reply({"error": str(error)}, 503)
                if self.path == "/api/install-update":
                    if not window or not getattr(sys, "frozen", False) or os.name != "nt":
                        raise ValueError("Automatic updates require the Windows desktop app.")
                    release = updates.latest_release()
                    if not release["available"]:
                        return self.reply({"message": "Zenshin is already up to date."})
                    app["running"] = False
                    cancel_analysis(app)
                    set_progress(app, "updating", detail="Downloading the latest Windows installer.")
                    try:
                        installer = updates.download_installer(release, lambda detail: set_progress(
                            app, "updating", detail=detail))
                        updates.launch_installer(installer, INSTALL_ROOT, args.port, args.state.resolve())
                    except (OSError, RuntimeError, ValueError, KeyError) as error:
                        app["error"] = str(error)
                        set_progress(app, "error", detail=str(error))
                        return self.reply(snapshot(app), 503)
                    self.reply({"message": "Installing update. Zenshin will close and reopen automatically."})
                    window.destroy()
                    return
                if self.path == "/api/check-connection":
                    return self.reply(check_codex_connection(app))
                if self.path == "/api/browser-action":
                    try:
                        return self.reply(browser_action(app, data))
                    except RuntimeError as error:
                        return self.reply({"error": str(error)}, 503)
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
                    targets, instructions = validate_settings(data)
                    browser = {key: data.get(key, False) for key in ("auto_password", "auto_terms")}
                    if any(type(value) is not bool for value in browser.values()):
                        raise ValueError("Browser automation toggles must be on or off")
                    if os.name != "nt" and any(browser.values()):
                        raise ValueError("Automatic Chrome actions are available on Windows only")
                    state = {**app["state"], "targets": targets, "instructions": instructions, **browser}
                    save_state(app["path"], state)
                    cancel_analysis(app)
                    app["state"] = state
                    app["running"] = False
                elif self.path == "/api/start":
                    start_monitoring(app)
                elif self.path == "/api/pause":
                    app["running"] = False
                    cancel_analysis(app)
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
        if getattr(sys, "frozen", False) and not args.no_browser:
            import webview
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                window = webview.create_window("Zenshin", f"http://127.0.0.1:{args.port}",
                                      width=1200, height=850, min_size=(850, 600))
                webview.start(gui="edgechromium", private_mode=False, icon=str(ROOT / "assets" / "zenshin.ico"),
                              storage_path=str(args.state.parent / "webview"))
            finally:
                server.shutdown()
                worker.join()
        else:
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
    try:
        main()
    except Exception as error:
        if getattr(sys, "frozen", False) and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), "Zenshin could not start", 0x10)
            sys.exit(1)
        raise
