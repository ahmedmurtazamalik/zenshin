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


