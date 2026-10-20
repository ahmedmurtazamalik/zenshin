"""Open the installed Windows desktop UI, check its controls, and close it normally."""

import ctypes
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
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
        expected = Icon(str(icon_path), actual.Size)
        actual_bitmap, expected_bitmap = actual.ToBitmap(), expected.ToBitmap()
        try:
            assert all(actual_bitmap.GetPixel(x, y).ToArgb() == expected_bitmap.GetPixel(x, y).ToArgb()
                       for x in range(actual.Width) for y in range(actual.Height)), f"Window {name} icon is not the Zenshin logo"
        finally:
            actual_bitmap.Dispose()
            expected_bitmap.Dispose()
            actual.Dispose()
            expected.Dispose()


def check(executable, installer=None):
    with tempfile.TemporaryDirectory(prefix="zenshin desktop ") as directory:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        state_path = Path(directory) / "state.json"
        bridge = None
        if installer:
            # A loaded MCP bridge must not prevent replacing the executable.
            bridge = subprocess.Popen([str(executable.with_name("Zenshin-bridge.exe"))],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            # Reproduce an update started by a onefile app that exits before restart.
            # The old app's extraction directory is gone by the time Setup reopens it.
            environment = dict(os.environ, _PYI_ARCHIVE_FILE=str(executable),
                               _PYI_APPLICATION_HOME_DIR=str(Path(directory) / "removed-parent-runtime"),
                               _PYI_PARENT_PROCESS_LEVEL="1")
            environment.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
            process = subprocess.Popen([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-",
                                        "/NORESTART", "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS",
                                        "/UPDATE=1", f"/DIR={executable.parent}", f"/PORT={port}",
                                        f"/STATE={state_path}"], env=environment)
        else:
            process = subprocess.Popen([str(executable), "--port", str(port), "--state", str(state_path)])
        try:
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
    check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None)
