import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import linux_ui


def thread(thread_id="selected", text="May I submit this application?"):
    return {"id": thread_id, "turns": [{"id": "turn-1", "items": [
        {"type": "agentMessage", "id": "message-1", "text": text}]}]}


