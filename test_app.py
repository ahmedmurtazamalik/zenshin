import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

import app
import linux_ui
import ai_decision
import zenshin_mcp


def thread(thread_id="selected", text="May I submit this application?"):
    return {"id": thread_id, "turns": [{"id": "turn-1", "items": [
        {"type": "agentMessage", "id": "message-1", "text": text}]}]}


class CodexSetupTests(unittest.TestCase):
    def setUp(self):
        guidance = patch.object(zenshin_mcp, "install_codex_guidance", return_value=Path("test/AGENTS.md"))
        self.guidance = guidance.start()
        self.addCleanup(guidance.stop)

    def test_standalone_registration_uses_executable_bridge_and_custom_port(self):
        import json
        import sys
        arguments = ["--port", "8879"]
        executable = str(Path(sys.executable).with_name("Zenshin-bridge.exe"))
        entry = {"name": "zenshin", "enabled": True,
                 "transport": {"command": executable, "args": arguments}}
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(ai_decision, "cli_command", return_value=["codex"]), \
             patch.object(app.subprocess, "run", side_effect=[
                 Mock(returncode=0, stdout="[]"), Mock(returncode=0, stdout=""),
                 Mock(returncode=0, stdout=json.dumps([entry]))]) as run:
            self.assertTrue(app.codex_setup(8879, register=True)["registered"])
            self.assertEqual(run.call_args_list[1].args[0],
                             ["codex", "mcp", "add", "zenshin", "--", executable, *arguments])
            self.guidance.assert_called_once_with()

    def test_chat_connection_check_reports_disconnected_live_and_failed_connection(self):
        monitor = {"connection": None, "running": False}
        self.assertFalse(app.check_codex_connection(monitor)["connected"])
        monitor["connection"] = Mock()
        with patch.object(app, "rpc", return_value={"data": []}) as rpc:
            self.assertTrue(app.check_codex_connection(monitor)["connected"])
            rpc.assert_called_once_with(monitor["connection"], "thread/list", {"limit": 1})
        monitor["running"] = True
        with patch.object(app, "rpc", side_effect=RuntimeError("Codex exited")), \
             patch.object(app, "cancel_analysis"), patch.object(app, "close_connection"):
            result = app.check_codex_connection(monitor)
            self.assertFalse(result["connected"])
            self.assertIn("Codex exited", result["message"])
            self.assertIsNone(monitor["connection"])
            self.assertFalse(monitor["running"])

    def test_registration_uses_current_paths_and_port_and_is_not_repeated(self):
        import json
        import sys
        arguments = ["-B", str(app.ROOT / "zenshin_mcp.py"), "--port", "8879"]
        entry = {"name": "zenshin", "enabled": True,
                 "transport": {"type": "stdio", "command": sys.executable, "args": arguments}}
        with patch.object(ai_decision, "cli_command", return_value=["codex"]), \
             patch.object(app.subprocess, "run", side_effect=[
                 Mock(returncode=0, stdout="[]"), Mock(returncode=0, stdout=""),
                 Mock(returncode=0, stdout=json.dumps([entry])),
                 Mock(returncode=0, stdout=json.dumps([entry]))]) as run:
            self.assertTrue(app.codex_setup(8879, register=True)["registered"])
            self.assertTrue(app.codex_setup(8879, register=True)["registered"])
            self.assertEqual(run.call_args_list[1].args[0],
                             ["codex", "mcp", "add", "zenshin", "--", sys.executable, *arguments])
            self.assertEqual(run.call_count, 4)

    def test_connect_replaces_old_registration_and_verifies_new_bridge(self):
        import json
        import sys
        executable = str(Path(sys.executable).with_name("Zenshin-bridge.exe"))
        old = {"name": "zenshin", "enabled": False, "transport": {"command": "old/Zenshin.exe", "args": ["--mcp"]}}
        new = {"name": "zenshin", "transport": {"command": executable, "args": []}}
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(ai_decision, "cli_command", return_value=["codex"]), \
             patch.object(app.subprocess, "run", side_effect=[
                 Mock(returncode=0, stdout=json.dumps([old])), Mock(returncode=0, stdout=""),
                 Mock(returncode=0, stdout=json.dumps([new]))]) as run:
            self.assertTrue(app.codex_setup(8765, register=True)["registered"])
            self.assertEqual(run.call_args_list[1].args[0], ["codex", "mcp", "add", "zenshin", "--", executable])

    def test_registration_check_preserves_conflict_and_cli_failure_has_manual_fallback(self):
        with patch.object(ai_decision, "cli_command", return_value=["codex"]), \
             patch.object(app.subprocess, "run", return_value=Mock(returncode=0,
                 stdout='[{"name":"zenshin","transport":{"command":"old-python","args":[]}}]')) as run:
            result = app.codex_setup(8765)
            self.assertTrue(result["conflict"])
            self.assertFalse(result["registered"])
            self.assertEqual(run.call_count, 1)
        with patch.object(ai_decision, "cli_command", side_effect=RuntimeError("CLI missing")):
            result = app.codex_setup(8879)
            self.assertIn("CLI missing", result["message"])
            self.assertIn("zenshin_mcp.py", result["command"])
            self.assertIn("8879", result["command"])

    def test_failed_guidance_repair_is_not_reported_as_successful_registration(self):
        import json
        import sys
        entry = {"name": "zenshin", "transport": {"command": sys.executable,
                 "args": ["-B", str(app.ROOT / "zenshin_mcp.py")]}}
        self.guidance.side_effect = OSError("Guidance file is not writable")
        with patch.object(ai_decision, "cli_command", return_value=["codex"]), \
             patch.object(app.subprocess, "run", return_value=Mock(returncode=0, stdout=json.dumps([entry]))):
            result = app.codex_setup(8765, register=True)
        self.assertFalse(result["registered"])
        self.assertIn("Guidance file is not writable", result["message"])


class StateTests(unittest.TestCase):
    def test_migrates_removed_modes_and_preserves_instructions_and_action_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            self.assertTrue(state["instructions"].strip())
            state.update(decision_method="exact", mode="preview", rules=[{"request": "Continue?", "response": "Yes"}],
                         instructions="Approve task-related requests.", activity=[{"status": "sent"}],
                         attempts={"browser:old": {"status": "sent"}})
            app.save_state(path, state)
            saved = app.load_state(path)
            self.assertTrue({"mode", "rules", "decision_method"}.isdisjoint(saved))
            self.assertEqual(saved["instructions"], "Approve task-related requests.")
            self.assertEqual(saved["activity"], [{"status": "sent"}])
            self.assertEqual(saved["attempts"], {"browser:old": {"status": "sent"}})


class UpdateRestoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"
        state = app.load_state(self.path)
        state.update(auto_password=True, targets=[{"id": "selected", "name": "Test chat"}])
        self.monitor = {"path": self.path, "state": state, "running": True,
                        "connection": object(), "error": ""}

    def test_update_handoff_is_saved_before_launch_and_restores_in_order_once(self):
        events = []
        def launch(*_args):
            self.assertFalse(self.monitor["running"])
            saved = app.load_state(self.path)
            self.assertEqual(saved["update_resume"], {"connected": True, "running": True})
            events.append("launch")
        with patch.object(app.updates, "download_installer", side_effect=lambda *_args: events.append("download") or Path("setup.exe")), \
             patch.object(app.updates, "launch_installer", side_effect=launch):
            app.install_update(self.monitor, {}, 8879)
        self.monitor.update(state=app.load_state(self.path), connection=None, running=False)
        connection = {"pending_read": None}
        with patch.object(app, "codex_setup", side_effect=lambda *_args, **_kwargs: events.append("register") or {"registered": True}) as setup, \
             patch.object(app.updates, "refresh_codex_mcp", side_effect=lambda: events.append("reload"), create=True), \
             patch.object(app, "connect", side_effect=lambda: events.append("connect") or connection), \
             patch.object(app, "verify_desktop_targets", side_effect=lambda *_args: events.append("verify")):
            result = app.restore_update(self.monitor, 8879)
        setup.assert_called_once_with(8879, register=True)
        self.assertEqual(events, ["download", "launch", "register", "reload", "connect", "verify"])
        self.assertTrue(result["state"]["running"])
        self.assertTrue(result["state"]["connected"])
        self.assertNotIn("update_resume", app.load_state(self.path))

    def test_update_preserves_paused_monitoring_and_chrome_only_connection_state(self):
        for connected, running in ((True, False), (False, True)):
            with self.subTest(connected=connected, running=running):
                self.monitor.update(running=False, connection=None)
                self.monitor["state"].update(targets=[], update_resume={"connected": connected, "running": running})
                with patch.object(app, "codex_setup", return_value={"registered": True}), \
                     patch.object(app.updates, "refresh_codex_mcp", create=True), \
                     patch.object(app, "connect", return_value={"pending_read": None}) as connect:
                    result = app.restore_update(self.monitor, 8879)
                self.assertEqual(result["state"]["running"], running)
                self.assertEqual(result["state"]["connected"], connected)
                self.assertEqual(connect.call_count, int(connected))

    def test_failed_refresh_consumes_handoff_and_does_not_resume_or_reconnect(self):
        self.monitor.update(running=False, connection=None)
        self.monitor["state"]["update_resume"] = {"connected": True, "running": True}
        with patch.object(app, "codex_setup", return_value={"registered": True}), \
             patch.object(app.updates, "refresh_codex_mcp", side_effect=RuntimeError("Codex reload failed"), create=True), \
             patch.object(app, "connect") as connect, patch.object(app, "start_monitoring") as start:
            result = app.restore_update(self.monitor, 8879)
        connect.assert_not_called()
        start.assert_not_called()
        self.assertFalse(result["state"]["running"])
        self.assertIn("Codex reload failed", result["state"]["error"])
        self.assertIn("Zenshin was updated", result["message"])
        self.assertIn("Open Codex manually", result["message"])
        self.assertNotIn("update_resume", app.load_state(self.path))

    def test_failed_installer_launch_removes_resume_handoff(self):
        with patch.object(app.updates, "download_installer", return_value=Path("setup.exe")), \
             patch.object(app.updates, "launch_installer", side_effect=OSError("Could not launch")):
            with self.assertRaisesRegex(OSError, "Could not launch"):
                app.install_update(self.monitor, {}, 8879)
        self.assertFalse(self.monitor["running"])
        self.assertNotIn("update_resume", app.load_state(self.path))


class LatestMessageTests(unittest.TestCase):
    def test_uses_latest_turn_instead_of_an_old_request(self):
        data = thread()
        data["turns"].append({"id": "turn-2", "items": [
            {"type": "agentMessage", "id": "message-2", "text": "Application submitted."}]})
        self.assertEqual(app.latest_message(data)["text"], "Application submitted.")
        data["turns"].append({"id": "turn-3", "items": []})
        self.assertIsNone(app.latest_message(data))

    def test_connection_rejects_mutating_operations(self):
        with self.assertRaises(ValueError):
            app.rpc({}, "turn/start", {})


class ReadProgressTests(unittest.TestCase):
    def test_read_reports_waiting_and_received_data_then_clears_on_completion(self):
        connection = {"process": Mock(), "next_id": 0, "buffer": b""}
        monitor = {"running": True, "connection": connection}
        snapshots = []
        chunks = iter([b'{"id":1,"result":', b'{"thread":{}}}\n'])

        def receive(*args):
            snapshots.append(app.progress_snapshot(monitor)["read"])
            return next(chunks)

        with patch.object(app, "pipe_ready", return_value=True), \
             patch.object(app.os, "read", side_effect=receive):
            self.assertEqual(app.rpc(connection, "thread/read", {}), {"thread": {}})
        self.assertEqual(snapshots[0]["bytes"], 0)
        self.assertEqual(snapshots[0]["timeout"], 60)
        self.assertGreater(snapshots[1]["bytes"], 0)
        self.assertIsNone(app.progress_snapshot(monitor)["read"])

    def test_timeout_clears_loading_status(self):
        connection = {"process": Mock(), "next_id": 0, "buffer": b""}
        with patch.object(app.time, "monotonic", side_effect=[0, 61]):
            with self.assertRaisesRegex(RuntimeError, "within 60 seconds"):
                app.rpc(connection, "thread/read", {})
        self.assertIsNone(connection["pending_read"])


class DesktopTests(unittest.TestCase):
    def setUp(self):
        analysis = patch.object(app, "analyze_request", return_value={
            "decision": "approve", "response": "Yes", "reason": "Authorized by saved instructions."})
        self.analysis = analysis.start()
        self.addCleanup(analysis.stop)
        desktop = patch.object(app, "poll_desktop", side_effect=lambda monitor: app.check_desktop(monitor, linux_ui))
        desktop.start()
        self.addCleanup(desktop.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.empty_state = Path(directory.name) / "state.json"
        navigation = patch.object(linux_ui, "open_chat")
        self.open_chat = navigation.start()
        self.addCleanup(navigation.stop)
        pending = patch.object(linux_ui, "conversation_pending", return_value=False)
        pending.start()
        self.addCleanup(pending.stop)
        cards = patch.object(linux_ui, "approval_cards", return_value=[])
        cards.start()
        self.addCleanup(cards.stop)
        setup = patch.object(linux_ui, "chat_setup_ready", return_value=False)
        setup.start()
        self.addCleanup(setup.stop)

    def test_selected_chats_are_opened_in_order_before_inspection(self):
        state = app.load_state(self.empty_state)
        state.update(targets=[{"id": "first", "name": "First chat"},
                                             {"id": "second", "name": "Second chat"}])
        monitor = {"state": state, "running": True, "connection": None}
        events = []
        self.open_chat.side_effect = lambda identity, name, **kwargs: events.append(("open", identity))
        def read(_connection, _method, params):
            identity = params["threadId"]
            data = thread(identity, text="Work finished.")
            data["name"] = "First chat" if identity == "first" else "Second chat"
            return {"thread": data}
        def inspect(name):
            events.append(("inspect", name))
            return []
        with patch.object(app, "rpc", side_effect=read), \
             patch.object(linux_ui, "approval_cards", side_effect=inspect):
            app.poll(monitor)
        self.assertEqual(events, [("open", "first"), ("inspect", "First chat"),
                                  ("open", "second"), ("inspect", "Second chat")])

    def test_navigation_failure_pauses_before_inspection_or_response(self):
        state = app.load_state(self.empty_state)
        state.update(targets=[{"id": "selected", "name": "Test chat"}])
        data = thread(text="Continue?")
        data["name"] = "Test chat"
        monitor = {"state": state, "running": True, "connection": None}
        self.open_chat.side_effect = RuntimeError("Chat did not appear")
        with patch.object(app, "rpc", return_value={"thread": data}), \
             patch.object(linux_ui, "approval_cards") as inspect, \
             patch.object(linux_ui, "reply") as reply, \
             patch.object(linux_ui, "answer") as answer, \
             patch.object(linux_ui, "approve") as approve:
            with self.assertRaisesRegex(RuntimeError, "Chat did not appear"):
                app.poll(monitor)
            inspect.assert_not_called()
            reply.assert_not_called()
            answer.assert_not_called()
            approve.assert_not_called()
        self.assertFalse(monitor["running"])
        self.assertEqual(state["attempts"], {})

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

    def test_ordinary_reply_event_error_confirms_linkified_new_message_without_resending(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            response = "Open https://jobs.example.com/register\nContinue."
            state.update(targets=[{"id": "selected", "name": "Test chat"}])
            self.analysis.return_value["response"] = response
            data = thread(text="Continue test?")
            data["name"] = "Test chat"
            monitor = {"state": state, "path": path, "running": True, "connection": None}
            ui = Mock()
            ui.approval_cards.return_value = []
            ui.conversation_pending.return_value = True
            ui.chat_setup_ready.return_value = False
            def delivered_then_error(*args, **kwargs):
                data["turns"].append({"id": "continued", "items": [{"type": "userMessage", "content": [
                    {"text": "Open [https://jobs.example.com/register](https://jobs.example.com/register)\\\nContinue.\n"}]}]})
                raise RuntimeError("Event subscriber failed after Send")
            ui.reply.side_effect = delivered_then_error
            with patch.object(app, "rpc", return_value={"thread": data}):
                app.check_desktop(monitor, ui)
            ui.reply.assert_called_once()
            self.assertTrue(monitor["running"])
            attempt = next(iter(app.load_state(path)["attempts"].values()))
            self.assertEqual(attempt["status"], "sent")
            self.assertEqual(attempt["reply_confirmed_by"], "app_server")

    def test_delivery_is_recorded_before_sending_and_not_repeated_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            state.update(targets=[{"id": "selected", "name": "Test chat"}])
            data = thread(text="Complete test?")
            data["name"] = "Test chat"
            data["turns"][0]["items"][0]["questions"] = [
                {"title": "Complete test?", "options": ["Yes", "No"]}]
            monitor = {"state": state, "path": path, "running": True,
                       "connection": None}

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

    def test_uncertain_delivery_is_logged_without_blocking_restart_or_resending(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = app.load_state(path)
            state.update(targets=[{"id": "selected", "name": "Test chat"}])
            data = thread()
            data["name"] = "Test chat"
            data["turns"][0]["items"][0]["questions"] = [
                {"title": "Complete test?", "options": ["Yes", "No"]}]
            monitor = {"state": state, "path": path, "running": True,
                       "connection": Mock()}
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "pending", return_value=True), \
                 patch.object(linux_ui, "answer", side_effect=RuntimeError("Lost confirmation")) as send:
                app.poll(monitor)
                app.poll(monitor)
                send.assert_called_once()
            self.assertTrue(monitor["running"])
            monitor["state"] = app.load_state(path)
            self.assertEqual(monitor["state"]["activity"][0]["status"], "uncertain")
            monitor["running"] = False
            with patch.object(app, "rpc", side_effect=[{"data": [data]}, {"thread": data}]):
                app.start_monitoring(monitor)
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "pending", return_value=True), \
                 patch.object(linux_ui, "answer") as send:
                app.poll(monitor)
                send.assert_not_called()

    def test_ai_without_an_answer_and_pause_do_not_send(self):
        state = app.load_state(self.empty_state)
        state.update(targets=[{"id": "selected", "name": "Test chat"}])
        self.analysis.return_value = {"decision": "needs_input", "response": None, "reason": "Missing information."}
        data = thread()
        data["name"] = "Test chat"
        data["turns"][0]["items"][0]["questions"] = [
            {"title": "Complete test?", "options": ["Yes", "No"]}]
        monitor = {"state": state, "running": True, "connection": None}
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
            state.update(targets=[{"id": "selected", "name": "Test chat"}])
            self.analysis.side_effect = [
                {"decision": "approve", "response": "Yes"}, {"decision": "needs_input", "response": None},
                {"decision": "approve", "response": "Yes"}, {"decision": "continue", "response": "Continue"}]
            data = thread(text="First? Second?")
            data["name"] = "Test chat"
            data["turns"][0]["items"][0]["questions"] = [
                {"title": "First?", "options": ["Yes"]}, {"title": "Second?", "options": ["Continue"]}]
            monitor = {"state": state, "path": path, "running": True, "connection": None}
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "pending", return_value=True), \
                 patch.object(linux_ui, "answer") as send:
                app.poll(monitor)
                send.assert_not_called()
                self.assertEqual(state["attempts"], {})
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
            state.update(targets=[{"id": "selected", "name": "Test chat"}])
            data = thread(text="Continue?")
            data["name"] = "Test chat"
            monitor = {"state": state, "path": path, "running": True, "connection": None}
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
            state.update(targets=[{"id": "selected", "name": "Test chat"}])
            data = thread()
            data["name"] = "Test chat"
            monitor = {"state": state, "path": path, "running": True, "connection": None}
            def approve(*args, **kwargs):
                saved = app.load_state(path)
                self.assertEqual(next(iter(saved["attempts"].values()))["status"], "sending")
            with patch.object(app, "rpc", return_value={"thread": data}), \
                 patch.object(linux_ui, "approval_cards", return_value=[{"text": text, "options": ["Allow once"]}]), \
                 patch.object(linux_ui, "approve", side_effect=approve) as send:
                self.analysis.return_value["response"] = "Always allow"
                app.poll(monitor)
                send.assert_not_called()
                self.analysis.return_value["response"] = "Allow once"
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


class ChatNavigationTests(unittest.TestCase):
    def test_open_chat_skips_visible_chat_and_waits_for_requested_chat_to_load(self):
        with patch.object(linux_ui, "document", return_value=object()), \
             patch.object(linux_ui.subprocess, "run") as launch:
            linux_ui.open_chat("selected", "Test chat")
            launch.assert_not_called()
        on_open = Mock()
        with patch.object(linux_ui, "document", side_effect=[None, None, object()]) as visible, \
             patch.object(linux_ui.subprocess, "run") as launch, \
             patch.object(linux_ui.time, "sleep"):
            linux_ui.open_chat("selected/id", "Test chat", on_open=on_open)
        on_open.assert_called_once_with()
        self.assertEqual(launch.call_args.args[0], ["xdg-open", "codex://threads/selected%2Fid"])
        self.assertTrue(all(call.args == ("Test chat",) for call in visible.call_args_list))

    def test_open_chat_fails_if_requested_chat_never_appears(self):
        with patch.object(linux_ui, "document", return_value=None), \
             patch.object(linux_ui.subprocess, "run"), \
             patch.object(linux_ui.time, "monotonic", side_effect=[0, 0, 11]), \
             patch.object(linux_ui.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "selected chat did not appear"):
                linux_ui.open_chat("selected", "Test chat")


class AIDecisionTests(unittest.TestCase):
    def setUp(self):
        desktop = patch.object(app, "poll_desktop", side_effect=lambda monitor: app.check_desktop(monitor, linux_ui))
        desktop.start()
        self.addCleanup(desktop.stop)
        navigation = patch.object(linux_ui, "open_chat")
        navigation.start()
        self.addCleanup(navigation.stop)
        pending = patch.object(linux_ui, "conversation_pending", return_value=False)
        pending.start()
        self.addCleanup(pending.stop)
        cards = patch.object(linux_ui, "approval_cards", return_value=[])
        cards.start()
        self.addCleanup(cards.stop)
        setup = patch.object(linux_ui, "chat_setup_ready", return_value=False)
        setup.start()
        self.addCleanup(setup.stop)

    def monitor(self, path):
        state = app.load_state(path)
        state.update(instructions="Continue formatting the report.",
                     targets=[{"id": "selected", "name": "Test chat"}])
        data = thread(text="Shall I carry on?")
        data["name"] = "Test chat"
        data["turns"][0]["items"].insert(0, {"type": "userMessage", "id": "user-1",
            "content": [{"type": "text", "text": "Format the report."}]})
        data["turns"][0]["items"][-1]["questions"] = [{"title": "Shall I carry on?",
                                                                   "options": ["Yes, continue.", "No."]}]
        return {"state": state, "path": path, "running": True, "connection": None}, data

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
                    self.assertEqual(monitor["state"]["activity"][0]["reason"], decision["reason"])
                    self.assertEqual(monitor["state"]["activity"][0]["status"], "skipped")

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
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=.2):
                            break
                    except OSError:
                        self.assertIsNone(process.poll(), "Server exited before accepting connections")
                        time.sleep(.02)
                else:
                    self.fail("Server did not start")
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
