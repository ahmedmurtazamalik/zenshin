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
