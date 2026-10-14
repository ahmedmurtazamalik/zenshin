import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

import app
import linux_ui
import ai_decision


def thread(thread_id="selected", text="May I submit this application?"):
    return {"id": thread_id, "turns": [{"id": "turn-1", "items": [
        {"type": "agentMessage", "id": "message-1", "text": text}]}]}


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.rule = {"request": "May I submit this application?", "response": "Approved."}

    def test_matches_complete_request_but_not_factual_or_combined_questions(self):
        self.assertEqual(app.preview_latest(thread(text="May I submit\nthis application?"),
                                            [self.rule])["response"], "Approved.")
        for text in ["What is your salary expectation?",
                     "May I submit this application? Also accept these terms?"]:
            self.assertIsNone(app.preview_latest(thread(text=text), [self.rule])["response"])

    def test_uses_latest_turn_instead_of_old_matching_request(self):
        data = thread()
        data["turns"].append({"id": "turn-2", "items": [
            {"type": "agentMessage", "id": "message-2", "text": "Application submitted."}]})
        self.assertIsNone(app.preview_latest(data, [self.rule])["response"])
        data["turns"].append({"id": "turn-3", "items": []})
        self.assertIsNone(app.preview_latest(data, [self.rule]))

    def test_monitor_reads_only_selected_chat_and_preserves_history_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            state.update(targets=[{"id": "selected", "name": "Job search"}], rules=[self.rule])
            monitor = {"path": path, "state": state, "running": True,
                       "connection": None, "previews": []}
            with patch.object(app, "rpc", return_value={"thread": thread()}) as read:
                app.poll(monitor)
                read.assert_called_once_with(None, "thread/read",
                                             {"threadId": "selected", "includeTurns": True})
                monitor["state"] = app.load_state(path)
                app.poll(monitor)
                self.assertEqual(len(monitor["state"]["activity"]), 1)
                self.assertEqual(monitor["state"]["rules"], [self.rule])
                self.assertEqual(monitor["state"]["targets"][0]["id"], "selected")
                monitor["running"] = False
                read.reset_mock()
                app.poll(monitor)
                read.assert_not_called()

    def test_conflicting_rules_are_rejected(self):
        with self.assertRaises(ValueError):
            app.validate_settings({"targets": [], "rules": [self.rule, {
                "request": "May I submit\nthis application?", "response": "No."}]})

    def test_connection_rejects_mutating_operations(self):
        with self.assertRaises(ValueError):
            app.rpc({}, "turn/start", {})


class DesktopTests(unittest.TestCase):
    def setUp(self):
        pending = patch.object(linux_ui, "conversation_pending", return_value=False)
        pending.start()
        self.addCleanup(pending.stop)
        cards = patch.object(linux_ui, "approval_cards", return_value=[])
        cards.start()
        self.addCleanup(cards.stop)

    def test_custom_answer_is_read_back_before_send_and_preserves_existing_draft(self):
        doc, root = object(), object()
        entry, send = Mock(), Mock()
        api = Mock()
        draft = ""
        submitted = False

        def write(_entry, text):
            nonlocal draft
            draft = text
            return True

        def press(_button):
            nonlocal submitted
            submitted = True

        def matches(node, role, name):
            if role == "entry":
                return [entry] if name == "Or write your own response" else []
            if role == "push button":
                return [send]
            if role == "static" and submitted and node is doc:
                return [object()]
            return []

        api.Text.get_text.side_effect = lambda *_args: draft
        api.EditableText.set_text_contents.side_effect = write
        with patch.object(linux_ui, "document", return_value=doc), \
             patch.object(linux_ui, "card", side_effect=lambda *_args: (None, False) if submitted else (root, True)), \
             patch.object(linux_ui, "matching", side_effect=matches), \
             patch.object(linux_ui, "atspi", return_value=api), \
             patch.object(linux_ui, "press", side_effect=press) as activate:
            linux_ui.answer("Test chat", "Complete test?", "Custom answer")
            activate.assert_called_once_with(send)
            submitted = False
            draft = "User's unfinished answer"
            activate.reset_mock()
            api.EditableText.set_text_contents.reset_mock()
            with self.assertRaisesRegex(RuntimeError, "already contains a draft"):
                linux_ui.answer("Test chat", "Complete test?", "Custom answer")
            activate.assert_not_called()
            api.EditableText.set_text_contents.assert_not_called()

    def test_offered_choice_submits_once_and_confirms_new_answer_echo(self):
        before, after, root = object(), object(), object()
        option = Mock()
        option.get_state_set.return_value.contains.return_value = True
        submitted = False

        def press(_option):
            nonlocal submitted
            submitted = True

        def matches(node, role, name):
            if role == "radio button":
                return [option]
            # Before submission the choice text is inside the form. Afterward
            # the same text is echoed in a new user message, with no pending card.
            return [object()]

        with patch.object(linux_ui, "document", side_effect=lambda _name: after if submitted else before), \
             patch.object(linux_ui, "card", side_effect=lambda *_args: (None, False) if submitted else (root, True)), \
             patch.object(linux_ui, "matching", side_effect=matches), \
             patch.object(linux_ui, "atspi"), \
             patch.object(linux_ui, "press", side_effect=press) as activate:
            linux_ui.answer("Test chat", "Complete test?", "Yes")
            activate.assert_called_once_with(option)

    def test_readable_chat_omitted_from_inventory_can_be_bound_by_id(self):
        state = {"targets": [{"id": "selected", "name": "Test chat"}], "attempts": {}}
        monitor = {"state": state, "connection": None}
        with patch.object(app, "rpc", side_effect=[{"data": []}, {
                "thread": {"id": "selected", "name": "Test chat"}}]) as read:
            app.verify_desktop_targets(monitor)
            self.assertEqual(read.call_args.args[1], "thread/read")

    def test_delivery_is_recorded_before_sending_and_not_repeated_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            state.update(mode="desktop", targets=[{"id": "selected", "name": "Test chat"}],
                         rules=[{"request": "Complete test?", "response": "Yes"}])
            data = thread(text="Complete test?")
            data["name"] = "Test chat"
            data["turns"][0]["items"][0]["questions"] = [
                {"title": "Complete test?", "options": ["Yes", "No"]}]
            monitor = {"state": state, "path": path, "running": True,
                       "connection": None, "previews": []}

            def answer(*_args, **_kwargs):
                saved = app.load_state(path)
                self.assertEqual(saved["attempts"]["selected:message-1"]["status"], "sending")

            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "pending", return_value=True), \
                 patch.object(linux_ui, "answer", side_effect=answer) as send:
                app.poll(monitor)
                monitor["state"] = app.load_state(path)
                app.poll(monitor)
                send.assert_called_once_with("Test chat", "Complete test?", "Yes", on_progress=ANY)
                self.assertEqual(monitor["state"]["attempts"]["selected:message-1"]["status"], "sent")

    def test_uncertain_delivery_pauses_and_blocks_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            state.update(mode="desktop", targets=[{"id": "selected", "name": "Test chat"}],
                         rules=[{"request": "Complete test?", "response": "Yes"}])
            data = thread()
            data["name"] = "Test chat"
            data["turns"][0]["items"][0]["questions"] = [
                {"title": "Complete test?", "options": ["Yes", "No"]}]
            monitor = {"state": state, "path": path, "running": True,
                       "connection": None, "previews": []}
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "pending", return_value=True), \
                 patch.object(linux_ui, "answer", side_effect=RuntimeError("Lost confirmation")):
                with self.assertRaises(RuntimeError):
                    app.poll(monitor)
            self.assertFalse(monitor["running"])
            monitor["state"] = app.load_state(path)
            with patch.object(app, "rpc", side_effect=[{"data": [data]}, {"thread": data}]):
                with self.assertRaisesRegex(ValueError, "unconfirmed attempt"):
                    app.verify_desktop_targets(monitor)

    def test_unmatched_request_and_pause_do_not_send(self):
        state = app.load_state(Path("/nonexistent-approval-helper-test-state"))
        state.update(mode="desktop", targets=[{"id": "selected", "name": "Test chat"}],
                     rules=[{"request": "A different request?", "response": "Yes"}])
        data = thread()
        data["name"] = "Test chat"
        data["turns"][0]["items"][0]["questions"] = [
            {"title": "Complete test?", "options": ["Yes", "No"]}]
        monitor = {"state": state, "running": True, "connection": None, "previews": []}
        with patch.object(app, "rpc", return_value={"thread": data}) as read, \
             patch.object(linux_ui, "pending", return_value=True), \
             patch.object(linux_ui, "answer") as send:
            app.poll(monitor)
            send.assert_not_called()
            monitor["running"] = False
            read.reset_mock()
            app.poll(monitor)
            read.assert_not_called()

    def test_multi_question_requires_every_answer_before_one_journaled_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            state.update(mode="desktop", targets=[{"id": "selected", "name": "Test chat"}],
                         rules=[{"request": "First?", "response": "Yes"}])
            data = thread(text="First? Second?")
            data["name"] = "Test chat"
            data["turns"][0]["items"][0]["questions"] = [
                {"title": "First?", "options": ["Yes"]}, {"title": "Second?", "options": ["Continue"]}]
            monitor = {"state": state, "path": path, "running": True, "connection": None, "previews": []}
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "pending", return_value=True), \
                 patch.object(linux_ui, "answer") as send:
                app.poll(monitor)
                send.assert_not_called()
                self.assertEqual(state["attempts"], {})
                state["rules"].append({"request": "Second?", "response": "Continue"})
                app.poll(monitor)
                self.assertEqual(send.call_args_list[0].args, ("Test chat", "First?", "Yes", "Second?"))
                self.assertEqual(send.call_args_list[1].args, ("Test chat", "Second?", "Continue"))
                self.assertEqual(len(state["attempts"]), 1)
                app.poll(monitor)
                self.assertEqual(send.call_count, 2)

    def test_ordinary_reply_uses_same_durable_attempt_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            state.update(mode="desktop", targets=[{"id": "selected", "name": "Test chat"}],
                         rules=[{"request": "Continue?", "response": "Yes"}])
            data = thread(text="Continue?")
            data["name"] = "Test chat"
            monitor = {"state": state, "path": path, "running": True, "connection": None, "previews": []}
            def reply(*args, **kwargs):
                self.assertEqual(app.load_state(path)["attempts"]["selected:message-1"]["status"], "sending")
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "conversation_pending", return_value=True), \
                 patch.object(linux_ui, "reply", side_effect=reply) as send:
                app.poll(monitor)
                monitor["state"] = app.load_state(path)
                app.poll(monitor)
                send.assert_called_once_with("Test chat", "Continue?", "Yes", on_progress=ANY)

    def test_approval_card_allows_once_and_persists_before_action(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            text = "Run local receipt command?\npython3 receipt.py"
            state.update(mode="desktop", targets=[{"id": "selected", "name": "Test chat"}],
                         rules=[{"request": text, "response": "Allow once"}])
            data = thread()
            data["name"] = "Test chat"
            monitor = {"state": state, "path": path, "running": True, "connection": None, "previews": []}
            def approve(*args, **kwargs):
                saved = app.load_state(path)
                self.assertEqual(next(iter(saved["attempts"].values()))["status"], "sending")
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "approval_cards", return_value=[{"text": text, "options": ["Allow once"]}]), \
                 patch.object(linux_ui, "approve", side_effect=approve) as send:
                state["rules"][0]["response"] = "Always allow"
                app.poll(monitor)
                send.assert_not_called()
                state["rules"][0]["response"] = "Allow once"
                app.poll(monitor)
                monitor["state"] = app.load_state(path)
                app.poll(monitor)
                send.assert_called_once_with("Test chat", text, "Allow once", on_progress=ANY)

    def test_approval_detection_reads_card_context_and_excludes_chat_composer(self):
        def node(role, name, children=()):
            result = Mock()
            result.get_role_name.return_value = role
            result.get_name.return_value = name
            result.get_child_count.return_value = len(children)
            result.get_child_at_index.side_effect = lambda index: children[index]
            for child in children:
                child.get_parent.return_value = result
            return result
        allow = node("push button", "Allow once")
        form = node("form", "", [node("push button", "Deny"), allow])
        context = node("alert", "", [node("static", "Run command?"), node("static", "python3 receipt.py")])
        card = node("section", "", [context, form])
        doc = node("document web", "Test chat", [card])
        with patch.object(linux_ui, "document", return_value=doc):
            self.assertEqual(linux_ui.approval_forms("Test chat"), [
                {"text": "Run command?\npython3 receipt.py", "button": allow}])
            node("section", "", [context, form, node("entry", "Work with Codex")])
            self.assertEqual(linux_ui.approval_forms("Test chat"), [])

        # Captured request_permissions cards use a Permissions heading, not an alert.
        context = node("section", "", [node("static", "Permissions"),
                                         node("static", "Read the exact probe file?")])
        form = node("form", "", [node("push button", "Deny"), allow])
        card = node("section", "", [context, form])
        doc = node("document web", "Test chat", [card])
        with patch.object(linux_ui, "document", return_value=doc):
            self.assertEqual(linux_ui.approval_forms("Test chat"), [
                {"text": "Permissions\nRead the exact probe file?", "button": allow}])
            node("section", "", [context, form, node("entry", "Work with Codex")])
            self.assertEqual(linux_ui.approval_forms("Test chat"), [])

    def test_approval_rechecks_card_and_requires_same_chat_confirmation(self):
        button = Mock()
        with patch.object(linux_ui, "approval_forms", return_value=[]) as forms, \
             patch.object(linux_ui, "press") as send, \
             patch.object(linux_ui, "atspi"):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                linux_ui.approve("Test chat", "Command A", "Allow once")
            send.assert_not_called()
            forms.return_value = [{"text": "Command A", "button": button}]
            with patch.object(linux_ui, "document", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "chat changed"):
                    linux_ui.approve("Test chat", "Command A", "Allow once")
            send.assert_called_once_with(button)


class AIDecisionTests(unittest.TestCase):
    def setUp(self):
        pending = patch.object(linux_ui, "conversation_pending", return_value=False)
        pending.start()
        self.addCleanup(pending.stop)
        cards = patch.object(linux_ui, "approval_cards", return_value=[])
        cards.start()
        self.addCleanup(cards.stop)

    def monitor(self, path):
        state = app.load_state(path)
        state.update(decision_method="ai", mode="desktop", instructions="Continue formatting the report.",
                     targets=[{"id": "selected", "name": "Test chat"}])
        data = thread(text="Shall I carry on?")
        data["name"] = "Test chat"
        data["turns"][0]["items"].insert(0, {"type": "userMessage", "id": "user-1",
            "content": [{"type": "text", "text": "Format the report."}]})
        data["turns"][0]["items"][-1]["questions"] = [{"title": "Shall I carry on?",
                                                                   "options": ["Yes, continue.", "No."]}]
        return {"state": state, "path": path, "running": True, "connection": None,
                "previews": []}, data

    def test_ai_uses_context_and_sends_offered_choice_once_without_exact_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor, data = self.monitor(Path(directory) / "state.json")
            decision = {"decision": "continue", "response": "Yes, continue.",
                        "reason": "Formatting is authorized."}
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "pending", return_value=True), \
                 patch.object(linux_ui, "answer") as send, \
                 patch.object(ai_decision, "start", return_value={}) as start, \
                 patch.object(ai_decision, "result", return_value=decision):
                app.poll(monitor)
                send.assert_not_called()
                self.assertEqual(start.call_args.args[0]["messages"][0]["role"], "user")
                app.poll(monitor)
                send.assert_called_once_with("Test chat", "Shall I carry on?", "Yes, continue.", on_progress=ANY)
                monitor["state"] = app.load_state(monitor["path"])
                app.poll(monitor)
                start.assert_called_once()
                self.assertEqual(send.call_count, 1)

    def test_missing_information_never_sends(self):
        for decision in [{"decision": "needs_input", "response": None, "reason": "Salary is missing."}]:
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory:
                monitor, data = self.monitor(Path(directory) / "state.json")
                with patch.object(app, "rpc", return_value={"thread": data}), \
                     patch.object(linux_ui, "pending", return_value=True), \
                     patch.object(linux_ui, "answer") as send, \
                     patch.object(ai_decision, "start", return_value={}) as start, \
                     patch.object(ai_decision, "result", return_value=decision):
                    app.poll(monitor)
                    app.poll(monitor)
                    app.poll(monitor)
                    send.assert_not_called()
                    start.assert_called_once()
                    self.assertEqual(monitor["previews"][0]["reason"], decision["reason"])

    def test_pause_cancels_analysis_and_does_not_poll_or_send(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor, data = self.monitor(Path(directory) / "state.json")
            monitor["analysis"] = {"key": "pending"}
            with patch.object(ai_decision, "cancel") as cancel, \
                 patch.object(app, "rpc") as read, patch.object(linux_ui, "answer") as send:
                monitor["running"] = False
                app.cancel_analysis(monitor)
                app.poll(monitor)
                cancel.assert_called_once_with({"key": "pending"})
                read.assert_not_called()
                send.assert_not_called()

    def test_invalid_model_decision_is_rejected_and_temporary_files_cleaned(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        (root / "decision.json").write_text('{"decision":"approve","response":null,"reason":"Yes"}')
        process = Mock()
        process.poll.return_value = 0
        process.returncode = 0
        job = {"process": process, "directory": directory,
               "output": (root / "events").open("w+"), "errors": (root / "errors").open("w+")}
        with self.assertRaisesRegex(RuntimeError, "invalid decision"):
            ai_decision.result(job)
        self.assertFalse(root.exists())


class ServerTests(unittest.TestCase):
    def test_progress_remains_readable_during_slow_check_and_pause_waits(self):
        import json
        import socket
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        entered, release, created, paused = (threading.Event() for _ in range(4))
        servers, results = [], {}
        server_class = app.ThreadingHTTPServer
        def make_server(*args):
            server = server_class(*args)
            servers.append(server)
            created.set()
            return server
        def slow_check(monitor):
            monitor["running"] = True
            app.set_progress(monitor, "reading", "Slow test chat")
            entered.set()
            release.wait(3)
        def post(path):
            with urlopen(Request(base + "/api/" + path, data=b"{}",
                                 headers={"Content-Type": "application/json"}), timeout=4) as response:
                results[path] = json.load(response)
            if path == "pause":
                paused.set()

        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            with patch.object(app, "ThreadingHTTPServer", side_effect=make_server), \
                 patch.object(app, "poll", side_effect=slow_check), patch("builtins.print"), \
                 patch("sys.argv", ["app.py", "--port", str(port), "--state", str(Path(directory) / "state.json")]):
                main = threading.Thread(target=app.main, daemon=True)
                main.start()
                try:
                    self.assertTrue(created.wait(2))
                    checking = threading.Thread(target=post, args=("poll",))
                    checking.start()
                    self.assertTrue(entered.wait(2))
                    pausing = threading.Thread(target=post, args=("pause",))
                    pausing.start()
                    with urlopen(base + "/api/progress", timeout=.5) as response:
                        progress = json.load(response)
                    self.assertEqual((progress["stage"], progress["chat"]), ("reading", "Slow test chat"))
                    self.assertFalse(paused.wait(.05))
                    release.set()
                    checking.join(2)
                    pausing.join(2)
                    self.assertTrue(paused.is_set())
                    self.assertFalse(results["pause"]["running"])
                    def failed_check(monitor):
                        app.set_progress(monitor, "error", "Slow test chat", "Chat unavailable")
                        raise RuntimeError("Chat unavailable")
                    with patch.object(app, "poll", side_effect=failed_check):
                        with self.assertRaises(HTTPError):
                            post("poll")
                    with patch.object(app, "poll", return_value=None):
                        post("poll")
                    self.assertEqual(results["poll"]["error"], "Chat unavailable")
                    self.assertEqual(results["poll"]["progress"]["stage"], "error")
                finally:
                    release.set()
                    if servers:
                        servers[0].shutdown()
                    main.join(2)

    def test_idle_browser_connection_does_not_block_loading_page(self):
        import select
        import socket
        import subprocess
        import sys
        import time
        from urllib.request import urlopen

        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            process = subprocess.Popen([sys.executable, str(app.ROOT / "app.py"),
                                        "--port", str(port), "--state", str(Path(directory) / "state.json")],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 5)[0], "Server did not start")
                self.assertIn(b"Zenshin", process.stdout.readline())
                with socket.create_connection(("127.0.0.1", port), timeout=5):
                    time.sleep(0.05)
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"Zenshin", response.read())
            finally:
                process.terminate()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
