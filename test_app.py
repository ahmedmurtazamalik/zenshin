import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import linux_ui


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
                return [entry]
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

