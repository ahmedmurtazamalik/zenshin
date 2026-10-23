"""Open the installed Windows desktop UI, check its controls, and close it normally."""

import ctypes
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

import uiautomation as ui


def check_window_icons(window, icon_path):
    # pythonnet is already installed by pywebview on Windows.
    import clr
    clr.AddReference("System.Drawing")
    from System import IntPtr
    from System.Drawing import Icon

    user = ctypes.WinDLL("user32")
    user.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
    user.SendMessageW.restype = ctypes.c_void_p
    for kind, name in ((0, "small"), (1, "large")):
        handle = user.SendMessageW(window.NativeWindowHandle, 0x7F, kind, 0)  # WM_GETICON
        assert handle, f"Window has no {name} icon"
        actual = Icon.FromHandle(IntPtr(handle))
        source = Icon(str(icon_path))
        expected = Icon(source, actual.Size) if kind == 0 else source.Clone()
        expected_native = Icon.FromHandle(expected.Handle)
        actual_bitmap, expected_bitmap = actual.ToBitmap(), expected_native.ToBitmap()
        try:
            assert actual.Size == expected.Size, f"Window {name} icon size is {actual.Size}, expected {expected.Size}"
            differences = sum(actual_bitmap.GetPixel(x, y).ToArgb() != expected_bitmap.GetPixel(x, y).ToArgb()
                              for x in range(actual.Width) for y in range(actual.Height))
            assert not differences, f"Window {name} icon ({actual.Size}) differs from Zenshin at {differences} pixels"
        finally:
            actual_bitmap.Dispose()
            expected_bitmap.Dispose()
            actual.Dispose()
            expected_native.Dispose()
            expected.Dispose()
            source.Dispose()


def finish_interactive_update(process):
    deadline = time.monotonic() + 60
    setup = ui.WindowControl(ClassName="TWizardForm", searchDepth=1)
    last_controls = []
    while time.monotonic() < deadline:
        assert process.poll() is None, "Installer exited before its Finish page was checked"
        if not setup.Exists(.2, .1):
            time.sleep(.1)
            continue
        controls = [control for control, _ in ui.WalkControl(setup, maxDepth=10)
                    if control.IsEnabled and not control.IsOffscreen]
        last_controls = [(control.ControlTypeName, control.Name) for control in controls]
        buttons = {re.sub(r"[&>\s]", "", control.Name).casefold(): control for control in controls
                   if control.ControlTypeName == "ButtonControl"}
        if "finish" in buttons:
            choices = [control for control in controls
                       if control.Name.replace("&", "").strip() == "Finish update and reconnect Codex (restarts Codex)"]
            assert len(choices) == 1, f"Finish reconnect checkbox missing or ambiguous: {last_controls}"
            toggle = choices[0].GetTogglePattern()
            checked = toggle.ToggleState == 1 if toggle else bool(choices[0].GetLegacyIAccessiblePattern().State & 0x10)
            assert checked, "Finish update and reconnect Codex must be selected by default"
            buttons["finish"].GetInvokePattern().Invoke()
            print("Installer Finish passed: reconnect Codex checkbox present and selected; Finish invoked.")
            return
        for name in ("next", "install"):
            if name in buttons:
                buttons[name].GetInvokePattern().Invoke()
                break
        time.sleep(.2)
    windows = [(control.Name, control.ClassName) for control in ui.GetRootControl().GetChildren()]
    raise RuntimeError(f"Interactive installer did not reach Finish within 60 seconds: {last_controls}; windows: {windows}")


def check(executable, installer=None, interactive=False):
    with tempfile.TemporaryDirectory(prefix="zenshin desktop ") as directory:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        state_path = Path(directory) / "state.json"
        bridge = None
        if installer:
            # Initialize the Python worker before updating its onefile executable.
            bridge = subprocess.Popen([str(executable.with_name("Zenshin-bridge.exe"))],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            bridge_lines = queue.Queue()
            def read_bridge():
                for line in bridge.stdout:
                    bridge_lines.put(line)
                bridge_lines.put(None)
            threading.Thread(target=read_bridge, daemon=True).start()
            initialize = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            bridge.stdin.write(initialize)
            bridge.stdin.flush()
            assert json.loads(bridge_lines.get(timeout=10))["result"]["serverInfo"]["name"] == "zenshin"
            # Reproduce an update started by a onefile app that exits before restart.
            # The old app's extraction directory is gone by the time Setup reopens it.
            environment = dict(os.environ, _PYI_ARCHIVE_FILE=str(executable),
                               _PYI_APPLICATION_HOME_DIR=str(Path(directory) / "removed-parent-runtime"),
                               _PYI_PARENT_PROCESS_LEVEL="1")
            environment.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
            arguments = [str(installer), "/SUPPRESSMSGBOXES", "/SP-", "/NORESTART",
                         "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS", "/UPDATE=1",
                         f"/DIR={executable.parent}", f"/PORT={port}", f"/STATE={state_path}"]
            if not interactive:
                arguments.insert(1, "/VERYSILENT")
            process = subprocess.Popen(arguments, env=environment)
        else:
            process = subprocess.Popen([str(executable), "--port", str(port), "--state", str(state_path)])
        try:
            if installer and interactive:
                finish_interactive_update(process)
            deadline = time.monotonic() + 45
            window = ui.WindowControl(Name="Zenshin", searchDepth=1)
            while not window.Exists(.2, .1):
                assert process.poll() in (None, 0) if installer else process.poll() is None, "Desktop app exited before opening its window"
                if time.monotonic() >= deadline:
                    raise RuntimeError("Desktop window did not appear")
                time.sleep(.1)
            skip = window.ButtonControl(Name="I'll explore", searchDepth=25)
            if skip.Exists(10, .2):
                skip.GetInvokePattern().Invoke()
            assert window.ButtonControl(Name="Save changes", searchDepth=25).Exists(10, .2), "Control page did not render"
            assert window.ButtonControl(Name="Start monitoring", searchDepth=25).Exists(2, .2), "Monitor controls missing"
            assert window.ButtonControl(Name="Check for updates", searchDepth=25).Exists(2, .2), "Update control missing"
            check_window_icons(window, executable.with_name("zenshin.ico"))
            if bridge:
                assert bridge.wait(timeout=10) is not None, "Installer left the old MCP bridge running"
                assert bridge_lines.get(timeout=10) is None, "Old MCP pipes stayed open after update"
                fresh = subprocess.run([str(executable.with_name("Zenshin-bridge.exe"))], input=initialize,
                                       capture_output=True, text=True, timeout=10)
                assert fresh.returncode == 0, fresh.stderr
                assert json.loads(fresh.stdout)["result"]["serverInfo"]["name"] == "zenshin"
            with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as response:
                assert response.status == 200
            window.GetWindowPattern().Close()
            assert process.wait(timeout=15) == 0, "Desktop window did not shut down cleanly"
            deadline = time.monotonic() + 15
            while True:
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", port)) != 0:
                        break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Server survived closing its window")
                time.sleep(.1)
        finally:
            if bridge:
                if bridge.poll() is None:
                    bridge.terminate()
                bridge.wait(timeout=10)
                bridge.stdin.close()
                bridge.stdout.close()
            if process.poll() is None:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, timeout=10)
                process.wait(timeout=10)
    print("Desktop passed: native window with Zenshin icons, rendered controls, local server, normal close and server shutdown.")


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None,
          interactive="--interactive" in sys.argv[3:])
