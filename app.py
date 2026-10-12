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


