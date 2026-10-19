"""Open the installed Windows desktop UI, check its controls, and close it normally."""

from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

import uiautomation as ui


def check(executable):
    with tempfile.TemporaryDirectory(prefix="zenshin desktop ") as directory:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen([str(executable), "--port", str(port),
                                    "--state", str(Path(directory) / "state.json")])
        try:
            deadline = time.monotonic() + 45
            window = ui.WindowControl(Name="Zenshin", searchDepth=1)
            while not window.Exists(.2, .1):
                assert process.poll() is None, "Desktop app exited before opening its window"
                if time.monotonic() >= deadline:
                    raise RuntimeError("Desktop window did not appear")
                time.sleep(.1)
            skip = window.ButtonControl(Name="I'll explore", searchDepth=25)
            if skip.Exists(10, .2):
                skip.GetInvokePattern().Invoke()
            assert window.ButtonControl(Name="Save changes", searchDepth=25).Exists(10, .2), "Control page did not render"
            assert window.ButtonControl(Name="Start monitoring", searchDepth=25).Exists(2, .2), "Monitor controls missing"
            with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as response:
                assert response.status == 200
            window.GetWindowPattern().Close()
            assert process.wait(timeout=15) == 0, "Desktop window did not shut down cleanly"
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", port)) != 0, "Server survived closing its window"
        finally:
            if process.poll() is None:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, timeout=10)
                process.wait(timeout=10)
    print("Desktop passed: native window, rendered controls, local server, normal close and server shutdown.")


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve())
