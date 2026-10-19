"""Check the packaged executable's assets, persistent settings, and MCP entry point."""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen


def check(executable, copy=True):
    with tempfile.TemporaryDirectory(prefix="zenshin bundle ") as directory:
        root = Path(directory)
        installed = root / executable.name if copy else executable
        if copy:
            shutil.copy2(executable, installed)
            shutil.copy2(executable.with_name("Zenshin-bridge.exe"), root / "Zenshin-bridge.exe")
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        # The child must not find a Python installation on PATH.
        environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32") if os.name == "nt" else "/nonexistent"
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        for first_launch in (True, False):
            with tempfile.TemporaryFile() as log:
                process = subprocess.Popen([str(installed), "--port", str(port), "--no-browser"],
                                           cwd=root.parent, env=environment, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 30
                    while True:
                        try:
                            with urlopen(url + "/api/state", timeout=1) as response:
                                state = json.load(response)
                            break
                        except OSError:
                            if process.poll() is not None or time.monotonic() >= deadline:
                                log.seek(0)
                                raise RuntimeError("Bundle failed to start: " + log.read().decode(errors="replace"))
                            time.sleep(.1)
                    assert not state["running"], "Bundle must start paused"
                    if first_launch:
                        for path in ("/", "/assets/zenshin.svg", "/assets/space-grotesk.ttf"):
                            with urlopen(url + path, timeout=5) as response:
                                assert response.read(), "Missing bundled asset: " + path
                        settings = {"targets": [], "rules": [], "instructions": "Bundle persistence check"}
                        request = Request(url + "/api/settings", data=json.dumps(settings).encode(),
                                          headers={"Content-Type": "application/json"})
                        with urlopen(request, timeout=5) as response:
                            assert response.status == 200
                        assert (installed.parent / ".local/state.json").is_file(), "Settings must live beside the executable"
                    else:
                        assert state["instructions"] == "Bundle persistence check", "Settings lost on restart"
                finally:
                    if os.name == "nt":
                        # PyInstaller's one-file bootloader owns a child process on Windows.
                        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                       check=True, stdout=subprocess.DEVNULL, timeout=10)
                    else:
                        process.terminate()
                    process.wait(timeout=10)

        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "check_chrome_terms", "arguments": {
                    "site": "https://example.com", "label": "Terms", "request_id": "bundle-check"}}},
        ]
        result = subprocess.run([str(installed.with_name("Zenshin-bridge.exe")), "--port", str(port)],
                                input="".join(json.dumps(message) + "\n" for message in messages),
                                capture_output=True, text=True, timeout=30, cwd=root.parent, env=environment)
        assert result.returncode == 0, result.stderr
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        assert replies[0]["result"]["serverInfo"]["name"] == "zenshin"
        assert len(replies[1]["result"]["tools"]) == 2
        # The server is stopped: the tool must report unavailability without attempting desktop actions.
        assert replies[2]["result"]["isError"]
        assert "Zenshin is unavailable" in replies[2]["result"]["content"][0]["text"]
    print("Bundle passed: startup without Python on PATH, assets, settings after restart, MCP discovery and transport.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--installed", action="store_true", help="Check the installed file in place")
    args = parser.parse_args()
    check(args.executable.resolve(), copy=not args.installed)
