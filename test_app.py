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

