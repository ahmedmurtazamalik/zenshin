"""Named Windows UI Automation controls for the native Codex desktop app."""

from concurrent.futures import ThreadPoolExecutor
import ctypes
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import quote, urlsplit

import ai_decision


def automation():
    try:
        import uiautomation
    except ImportError as error:
        raise RuntimeError("Windows desktop access needs: python -m pip install -r requirements-windows.txt") from error
    return uiautomation


_worker = None


def run(operation, *args, **kwargs):
    # The HTTP operation lock serializes callers. Keep the cached UIA client and
    # all its controls on one MTA thread for the lifetime of the server.
    global _worker
    api = automation()
    if _worker is None:
        _worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zenshin-uia",
                                     initializer=api.comtypes.CoInitializeEx, initargs=(0,))
    try:
        return _worker.submit(operation, *args, **kwargs).result()
    except api.comtypes.COMError as error:
        raise RuntimeError("Windows desktop controls became unavailable; inspect the chat manually") from error


def shutdown():
    global _worker
    if _worker is None:
        return
    def release():
        api = automation()
        api.uiautomation._AutomationClient._instance = None
        api.comtypes.CoUninitialize()
    try:
        _worker.submit(release).result()
    finally:
        _worker.shutdown()
        _worker = None


def process_path(identity):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, identity)
    if not handle:
        return ""
    try:
        path, size = ctypes.create_unicode_buffer(32768), ctypes.c_ulong(32768)
        if kernel.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, path, ctypes.byref(size)):
            return path.value
        return ""
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def nodes(root, stop_at_documents=False):
    if root is None:
        return
    if root.ControlTypeName == "GroupControl" and root.Name in {"Home", "App navigation"}:
        return
    yield root
    if stop_at_documents and root.ControlTypeName == "DocumentControl":
        return
    for child in root.GetChildren():
        yield from nodes(child, stop_at_documents)


def document(name):
    matches = []
    for window in automation().GetRootControl().GetChildren():
        path = process_path(window.ProcessId).lower()
        # This Codex distribution is called ChatGPT.exe inside OpenAI.Codex.
        if not (path.endswith("\\codex.exe") or
                (path.endswith("\\chatgpt.exe") and "\\openai.codex_" in path)):
            continue
        matches.extend(node for node in nodes(window, stop_at_documents=True)
                       if node.ControlTypeName == "DocumentControl" and node.Name == name
                       and not node.IsOffscreen)
    if len(matches) > 1:
        raise RuntimeError("This chat is open in multiple desktop windows; leave only one open")
    return matches[0] if matches else None


def codex_windows():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    handles = []
    def collect(handle, _):
        handles.append(handle)
        return True
    if not user32.EnumWindows(callback_type(collect), None):
        raise ctypes.WinError(ctypes.get_last_error())
    for handle in handles:
        if not user32.IsWindowVisible(handle):
            continue
        identity = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(identity))
        path = process_path(identity.value)
        lower = path.lower()
        if lower.endswith("\\codex.exe") or (lower.endswith("\\chatgpt.exe") and "\\openai.codex_" in lower):
            window = automation().ControlFromHandle(handle)
            if window is not None:
                yield window, path, identity.value


def restart_codex():
    api = automation()
    windows = list(codex_windows())
    if not windows:
        try:
            os.startfile("codex://")
        except OSError as error:
            raise RuntimeError("Could not open Codex for automatic reconnect: " + str(error)) from error
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            windows = list(codex_windows())
            if windows:
                break
            time.sleep(.25)
        if not windows:
            raise RuntimeError("Codex did not expose a window within 10 seconds; automatic reconnect was not confirmed")
    identities = {(os.path.normcase(path), identity) for _, path, identity in windows}
    if len(identities) != 1:
        raise RuntimeError("Several Codex instances are open; automatic reconnect could not identify one app")
    window, path, identity = windows[0]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    handle = kernel.OpenProcess(0x100000, False, identity)  # SYNCHRONIZE only.
    if not handle:
        raise RuntimeError("Could not watch Codex exit; automatic reconnect stopped")
    try:
        window.SetActive(waitTime=.1)
        window.SwitchToThisWindow(waitTime=.1)
        if not api.ControlsAreSame(api.GetForegroundControl(), window):
            raise RuntimeError("Codex could not take focus; no quit shortcut was sent")
        # Windows File > Quit. Closing its window can leave Codex running.
        api.SendKeys("{Ctrl}q", waitTime=.1)
        deadline = time.monotonic() + 30
        confirmed_quit = False
        while time.monotonic() < deadline:
            status = kernel.WaitForSingleObject(ctypes.c_void_p(handle), 0)
            if status == 0:
                break
            if status != 258:  # WAIT_TIMEOUT means the original process is alive.
                raise RuntimeError("Could not confirm whether Codex exited")
            try:
                foreground = api.GetForegroundControl()
                if not confirmed_quit and foreground is not None and foreground.ClassName == "#32770":
                    dialogs = [candidate for candidate, candidate_path, candidate_id in codex_windows()
                               if candidate_id == identity and os.path.normcase(candidate_path) == os.path.normcase(path)
                               and api.ControlsAreSame(candidate, foreground)]
                    buttons = [control for control in nodes(foreground, stop_at_documents=True)
                               if control.ControlTypeName == "ButtonControl" and control.IsEnabled and not control.IsOffscreen]
                    quit_buttons = [button for button in buttons if button.Name == "Quit"]
                    if dialogs and len(quit_buttons) == 1 and any(button.Name == "Cancel" for button in buttons):
                        confirmed_quit = True
                        press(quit_buttons[0])
            except api.comtypes.COMError:
                # Quit can destroy these controls before the process exits.
                # Its process handle, not UIA availability, confirms shutdown.
                pass
            time.sleep(.2)
        else:
            raise RuntimeError("Codex did not quit within 30 seconds; it was not forced closed or relaunched")
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.startfile("codex://")
    except OSError as error:
        raise RuntimeError("Codex closed but Windows could not reopen it: " + str(error)) from error
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(candidate_id != identity and os.path.normcase(candidate_path) == os.path.normcase(path)
               for _, candidate_path, candidate_id in codex_windows()):
            return True
        time.sleep(.25)
    raise RuntimeError("Codex was reopened but its new window was not confirmed within 30 seconds")


def open_chat(thread_id, name, on_open=None):
    doc = document(name)
    if doc is None:
        if on_open:
            on_open()
        try:
            os.startfile("codex://threads/" + quote(thread_id, safe=""))
        except OSError as error:
            raise RuntimeError("Could not open the selected chat in Codex: " + str(error)) from error
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            doc = document(name)
            if doc is not None:
                break
            time.sleep(.25)
        else:
            raise RuntimeError("The selected chat did not appear in Codex; check accessibility and open it manually")
    bottom = matching(doc, "ButtonControl", "Scroll to bottom")
    if len(bottom) == 1 and bottom[0].IsEnabled and not bottom[0].IsOffscreen:
        press(bottom[0])


def matching(root, role, name):
    return [node for node in nodes(root) if node.ControlTypeName == role and node.Name == name]


def answer_entries(root):
    return matching(root, "EditControl", "Or write your own response") + matching(root, "EditControl", "Reply…")


def card(doc, question):
    for entry in answer_entries(doc):
        parent = entry.GetParentControl()
        if matching(parent, "TextControl", question) and (matching(parent, "ButtonControl", "Send") or matching(parent, "ButtonControl", "Next")):
            return parent, True
    closed = [button.GetParentControl() for button in matching(doc, "ButtonControl", "Answer question")
              if matching(button.GetParentControl(), "TextControl", question)]
    if len(closed) > 1:
        raise RuntimeError("Several pending cards have the same question; answer them manually")
    return (closed[0], False) if closed else (None, False)


def pending(name, question):
    return card(document(name), question)[0] is not None


def press(button):
    if not button.IsEnabled or button.IsOffscreen:
        raise RuntimeError("The desktop response control is disabled or hidden")
    api = automation()
    invoke = button.GetPattern(api.PatternId.InvokePattern)
    if invoke:
        try:
            invoke.Invoke()
        except api.comtypes.COMError as error:
            # Chromium can submit then fail to notify a UIA event subscriber.
            # Never retry Invoke; the caller must still confirm the live result.
            if error.hresult != -2147220991:
                raise
        return
    selection = button.GetPattern(api.PatternId.SelectionItemPattern)
    if selection:
        selection.Select()
        return
    raise RuntimeError("The desktop control does not expose an Invoke or Selection action")


def site_origin(address):
    parsed = urlsplit(address if "://" in address else "https://" + address)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter the registration site's http:// or https:// address")
    port = parsed.port
    suffix = f":{port}" if port and port != {"http": 80, "https": 443}[parsed.scheme] else ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{suffix}"


def chrome_windows():
    # The desktop UIA sibling walker can stall on unrelated applications.
    # Enumerate native windows first and ask UIA only about visible Chrome ones.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    handles = []
    def collect(handle, _):
        handles.append(handle)
        return True
    if not user32.EnumWindows(callback_type(collect), None):
        raise ctypes.WinError(ctypes.get_last_error())
    for handle in handles:
        if not user32.IsWindowVisible(handle):
            continue
        identity = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(identity))
        if process_path(identity.value).lower().endswith("\\chrome.exe"):
            window = automation().ControlFromHandle(handle)
            if window is not None:
                yield window


def chrome_password_suggestion(origin):
    matches, browsers = [], []
    api = automation()
    for window in chrome_windows():
        if window.IsOffscreen:
            continue
        # Browser chrome only: never inspect webpage controls or password fields.
        native = list(nodes(window, stop_at_documents=True))
        addresses = [node for node in native if node.ControlTypeName == "EditControl"
                     and node.Name == "Address and search bar"]
        if len(addresses) != 1:
            continue
        # The omnibox omits schemes and sometimes "www". Read only the native
        # document URL, without traversing webpage controls or password fields.
        origins = []
        for node in native:
            if node.ControlTypeName != "DocumentControl" or node.IsOffscreen:
                continue
            value = node.GetPattern(api.PatternId.ValuePattern)
            if value and value.Value.startswith(("http://", "https://")):
                origins.append(site_origin(value.Value))
        if origins != [origin]:
            continue
        browsers.append(window)
        for node in native:
            if node.IsOffscreen or not node.IsEnabled or node.ControlTypeName not in {"MenuItemControl", "ButtonControl", "ListItemControl"}:
                continue
            # Chrome can append the generated password to the accessible name.
            # Match the label prefix, and never return or log that name.
            label = node.Name.casefold()
            if any(label == text or label.startswith(text + " ") for text in
                   ("use strong password", "use suggested password")):
                matches.append(node)
    if len(browsers) > 1 or len(matches) > 1:
        raise RuntimeError("Several Chrome windows or password suggestions match this site; leave only one open")
    return (browsers[0] if browsers else None, matches[0] if matches else None)


def prepare_chrome_site(address, open_site=True):
    address = address.strip()
    origin = site_origin(address)
    if "://" not in address:
        address = "https://" + address
    requested = urlsplit(address)
    opened, stable_url = False, None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            browser, _ = chrome_password_suggestion(origin)
            native = list(nodes(browser, stop_at_documents=True)) if browser else []
        except automation().comtypes.COMError:
            # Chrome can replace its accessibility elements while a page opens.
            time.sleep(.25)
            continue
        documents = [control for control in native
                     if control.ControlTypeName == "DocumentControl" and not control.IsOffscreen]
        # Chrome's native WebView containers also report DocumentControl, but
        # expose no URL. Count only actual HTTP(S) page documents.
        documents = [control for control in documents
                     if (pattern := control.GetPattern(automation().PatternId.ValuePattern))
                     and pattern.Value.startswith(("http://", "https://"))]
        value = documents[0].GetPattern(automation().PatternId.ValuePattern) if len(documents) == 1 else None
        current_url = value.Value if value else ""
        current = urlsplit(current_url)
        same_page = opened or (requested.path in {"", "/"} and not requested.query) or (
            current.path == requested.path and current.query == requested.query)
        if browser and same_page:
            buttons = {control.Name for control in native if control.ControlTypeName == "ButtonControl"
                       and control.IsEnabled and not control.IsOffscreen}
            ready = (current_url.startswith(("http://", "https://")) and site_origin(current_url) == origin
                     and documents[0].IsEnabled
                     and bool(buttons & {"Reload", "Reload this page"})
                     and not buttons & {"Stop", "Stop loading"})
            if ready and stable_url == current_url:
                return {"message": f"Chrome is on {origin} and has finished loading. Zenshin can perform the requested native action."}
            stable_url = current_url if ready else None
        elif open_site and not opened:
            chrome = ""
            for window in automation().GetRootControl().GetChildren():
                path = process_path(window.ProcessId)
                if path.lower().endswith("\\chrome.exe"):
                    chrome = path
                    break
            if not chrome:
                import winreg
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    try:
                        chrome = winreg.QueryValue(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
                        if chrome.lower().endswith("\\chrome.exe"):
                            break
                        chrome = ""
                    except OSError:
                        pass
            if not chrome:
                raise RuntimeError("Chrome was not found; open Chrome and try preparing the site again")
            subprocess.Popen([chrome, address])
            opened, stable_url = True, None
        else:
            stable_url = None
        time.sleep(.25)
    raise RuntimeError("Chrome site is not ready: check the address, loading indicator, and any redirects before trying again")


def chrome_page_controls(browser, origin):
    api = automation()
    for doc in nodes(browser, stop_at_documents=True):
        if doc.ControlTypeName != "DocumentControl" or doc.IsOffscreen:
            continue
        value = doc.GetPattern(api.PatternId.ValuePattern)
        if value and value.Value.startswith(("http://", "https://")) and site_origin(value.Value) == origin:
            yield from nodes(doc)


def chrome_control_description(control):
    # Labels and nearby static text only. Never read editable content or values.
    def text_nodes(root):
        if root.ControlTypeName == "EditControl":
            return
        if root.ControlTypeName in {"TextControl", "HyperlinkControl"}:
            yield root.Name
        for child in root.GetChildren():
            yield from text_nodes(child)

    nearby = []
    parent = control.GetParentControl()
    for _ in range(2):
        if parent is None or parent.ControlTypeName in {"DocumentControl", "WindowControl"}:
            break
        nearby = list(text_nodes(parent))
        if nearby:
            break
        parent = parent.GetParentControl()
    return {"name": control.Name, "help_text": control.HelpText,
            "automation_id": control.AutomationId,
            "nearby_text": " ".join(nearby)[:2000]}


def chrome_new_password_field(browser, origin):
    fields = [control for control in chrome_page_controls(browser, origin)
              if control.ControlTypeName == "EditControl" and control.IsPassword
              and control.IsEnabled and not control.IsOffscreen]
    if not fields:
        raise RuntimeError("Cannot identify one new-password field; inspect Chrome manually")
    descriptions = [chrome_control_description(field) for field in fields]
    selected = ai_decision.select_browser_control("password", descriptions, hint=browser.Name)
    if selected is None:
        raise RuntimeError("Cannot identify one new-password field; inspect Chrome manually")
    field = fields[selected]
    if (field.ControlTypeName != "EditControl" or not field.IsPassword
            or not field.IsEnabled or field.IsOffscreen
            or chrome_control_description(field) != descriptions[selected]):
        raise RuntimeError("Chrome's password field changed; nothing was selected")
    return {"control": field, "description": descriptions[selected]}


def focus_chrome_password_field(browser, field):
    # DOM focus can move while Chrome is in the background. Confirm Windows
    # keyboard focus after activating Chrome, allowing its UIA event to arrive.
    browser.SetActive(waitTime=.1)
    field.SetFocus()
    if field.HasKeyboardFocus:
        return
    deadline = time.monotonic() + 2
    while not field.HasKeyboardFocus:
        if time.monotonic() >= deadline:
            raise RuntimeError("Chrome did not focus the new-password field")
        time.sleep(.1)


def open_chrome_password_suggestion(address):
    origin = site_origin(address)
    browser, suggestion = chrome_password_suggestion(origin)
    if browser is None:
        raise RuntimeError("The requested Chrome page is not available")
    api = automation()
    selection = chrome_new_password_field(browser, origin)
    field = selection["control"]
    # Classification can take time: check the site and control again before focus.
    prepare_chrome_site(address, open_site=False)
    current_browser, _ = chrome_password_suggestion(origin)
    if (not api.ControlsAreSame(browser, current_browser)
            or not any(api.ControlsAreSame(field, control) for control in chrome_page_controls(current_browser, origin))
            or field.ControlTypeName != "EditControl" or not field.IsPassword
            or not field.IsEnabled or field.IsOffscreen
            or chrome_control_description(field) != selection["description"]):
        raise RuntimeError("Chrome's password field changed; nothing was selected")
    focus_chrome_password_field(browser, field)
    if chrome_password_suggestion(origin)[1] is not None:
        return selection
    # Invoke Chrome's native context menu, without keyboard or coordinate input.
    interface = api.uiautomation._AutomationClient.instance().UIAutomationCore.IUIAutomationElement3
    field.Element.QueryInterface(interface).ShowContextMenu()
    browser, _ = chrome_password_suggestion(origin)
    commands = [control for control in nodes(browser, stop_at_documents=True)
                if control.ControlTypeName == "MenuItemControl" and control.IsEnabled
                and not control.IsOffscreen and control.Name.casefold().rstrip(".\u2026")
                in {"suggest password", "suggest strong password"}]
    if len(commands) != 1:
        raise RuntimeError("Chrome's native Suggest password command is unavailable; check Chrome manually")
    prepare_chrome_site(address, open_site=False)
    press(commands[0])
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if chrome_password_suggestion(origin)[1] is not None:
            return selection
        time.sleep(.2)
    raise RuntimeError("Chrome did not open its native password suggestion; check Chrome manually")


def chrome_password_filled(browser, origin, field=None):
    api = automation()
    fields = [control for control in chrome_page_controls(browser, origin)
              if control.ControlTypeName == "EditControl" and control.IsPassword
              and control.IsEnabled and not control.IsOffscreen
              and (field is None or api.ControlsAreSame(field, control))]
    if not fields:
        return False
    for field in fields:
        text = field.GetPattern(api.PatternId.TextPattern)
        if not text:
            return False
        # Chrome exposes one embedded-object unit even for an empty field.
        # Check beyond that unit without fetching password text/value.
        extent = text.DocumentRange.textRange
        content = extent.Clone()
        content.MoveEndpointByUnit(0, 0, 1)
        if content.CompareEndpoints(0, extent, 1) >= 0:
            return False
    return True


def accept_chrome_password(address, selection=None):
    origin = site_origin(address.strip())
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        browser, suggestion = chrome_password_suggestion(origin)
        if suggestion is not None:
            if selection is None:
                selection = chrome_new_password_field(browser, origin)
                field = selection["control"]
                focus_chrome_password_field(browser, field)
            field = selection["control"]
            # Re-read the site and native popup immediately before activation.
            current_browser, current = chrome_password_suggestion(origin)
            api = automation()
            if (current is None or not api.ControlsAreSame(browser, current_browser)
                    or not api.ControlsAreSame(suggestion, current)):
                raise RuntimeError("Chrome's password suggestion changed; nothing was selected")
            if (not any(api.ControlsAreSame(field, control) for control in chrome_page_controls(browser, origin))
                    or field.ControlTypeName != "EditControl" or not field.IsPassword
                    or not field.IsEnabled or field.IsOffscreen
                    or chrome_control_description(field) != selection["description"]):
                raise RuntimeError("Chrome's password field changed; nothing was selected")
            press(current)  # Exactly one activation; never retry an uncertain result.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                current_browser, remaining = chrome_password_suggestion(origin)
                if current_browser is None or not api.ControlsAreSame(browser, current_browser):
                    raise RuntimeError("Chrome's site changed after activation; inspect Chrome before trying again")
                if remaining is None and chrome_password_filled(current_browser, origin, field):
                    time.sleep(.3)
                    if chrome_password_filled(current_browser, origin, field):
                        return {"message": "Chrome's generated password field remained filled after acceptance."}
                    break
                time.sleep(.2)
            raise RuntimeError("Chrome's password fields did not remain filled after selection; do not retry this action")
        time.sleep(.2)
    raise RuntimeError("No supported Chrome password suggestion appeared for this site within 30 seconds; nothing was selected")


def chrome_signup_request(origin, password=False, terms=False, label=None):
    browser, suggestion = chrome_password_suggestion(origin)
    if password and suggestion is not None:
        return {"kind": "password", "label": "Chrome suggested password"}
    if not terms or browser is None:
        return None
    api = automation()
    controls = [control for control in chrome_page_controls(browser, origin)
                if control.ControlTypeName == "CheckBoxControl" and control.IsEnabled
                and (toggle := control.GetPattern(api.PatternId.TogglePattern)) and toggle.ToggleState == 0]
    if not controls:
        return None
    descriptions = [chrome_control_description(control) for control in controls]
    selected = ai_decision.select_browser_control("terms", descriptions, hint=label or "")
    if selected is None:
        return None
    return {"kind": "terms", "label": controls[selected].Name,
            "control": controls[selected], "description": descriptions[selected]}


def perform_chrome_signup_request(origin, request):
    if request["kind"] == "password":
        return accept_chrome_password(origin, request.get("field"))
    browser, _ = chrome_password_suggestion(origin)
    controls = [control for control in chrome_page_controls(browser, origin) if control.ControlTypeName == "CheckBoxControl"
                and automation().ControlsAreSame(control, request["control"])
                and control.IsEnabled]
    if len(controls) != 1:
        raise RuntimeError("The terms checkbox changed or is ambiguous; inspect Chrome manually")
    toggle = controls[0].GetPattern(automation().PatternId.TogglePattern)
    if (not toggle or toggle.ToggleState != 0
            or chrome_control_description(controls[0]) != request["description"]):
        raise RuntimeError("The terms checkbox changed; nothing was selected")
    if controls[0].IsOffscreen:
        scroll = controls[0].GetPattern(automation().PatternId.ScrollItemPattern)
        if not scroll:
            raise RuntimeError("The terms checkbox is offscreen and cannot be scrolled into view")
        scroll.ScrollIntoView()
        current_browser, _ = chrome_password_suggestion(origin)
        if (current_browser is None or not automation().ControlsAreSame(browser, current_browser)
                or not any(automation().ControlsAreSame(control, controls[0])
                           for control in chrome_page_controls(current_browser, origin))
                or not controls[0].IsEnabled or toggle.ToggleState != 0
                or chrome_control_description(controls[0]) != request["description"]):
            raise RuntimeError("The terms checkbox changed after scrolling; nothing was selected")
        if controls[0].IsOffscreen:
            raise RuntimeError("The terms checkbox remained offscreen; nothing was selected")
    toggle.Toggle()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current_browser, _ = chrome_password_suggestion(origin)
        if current_browser is None or not automation().ControlsAreSame(browser, current_browser):
            break
        if toggle.ToggleState == 1:
            return
        time.sleep(.2)
    raise RuntimeError("Terms checkbox selection was not confirmed; inspect Chrome before trying again")


def chrome_captcha_region(browser, origin):
    controls = list(chrome_page_controls(browser, origin))
    regions = []
    for control in controls[1:]:  # Never treat the whole account page as a puzzle.
        if (control.ControlTypeName not in {"DocumentControl", "PaneControl", "GroupControl"}
                or control.IsOffscreen or not control.IsEnabled):
            continue
        label = control.Name.casefold()
        if control.ControlTypeName == "DocumentControl":
            value = control.GetPattern(automation().PatternId.ValuePattern)
            label += " " + (value.Value if value else "").casefold()
        if re.search(r"captcha|challenges\.cloudflare\.com|arkoselabs|funcaptcha|human verification", label):
            rectangle = control.BoundingRectangle
            if rectangle.width() > 0 and rectangle.height() > 0:
                regions.append(control)
    if not regions:
        raise RuntimeError("No visible CAPTCHA frame or container is available; invisible checks are unsupported")
    # An open image challenge is larger than its checkbox widget. Drop nested
    # duplicates, but do not choose between unrelated challenges on the page.
    outer = [control for control in regions if not any(
        not automation().ControlsAreSame(control, other)
        and any(automation().ControlsAreSame(control, child) for child in nodes(other))
        for other in regions)]
    if len(outer) > 1:
        outer.sort(key=lambda control: control.BoundingRectangle.width() * control.BoundingRectangle.height(), reverse=True)
        if outer[0].BoundingRectangle.height() <= 150 or outer[1].BoundingRectangle.height() > 150:
            raise RuntimeError("Several CAPTCHA challenges are visible; the target is ambiguous")
    return outer[0]


def chrome_captcha_snapshot(browser, region, path):
    api = automation()
    if not api.ControlsAreSame(api.GetForegroundControl(), browser):
        raise RuntimeError("Chrome is not the foreground window; CAPTCHA action stopped")
    rectangle, window = region.BoundingRectangle, browser.BoundingRectangle
    left, top, right, bottom = rectangle.left, rectangle.top, rectangle.right, rectangle.bottom
    if (region.IsOffscreen or not region.IsEnabled or right <= left or bottom <= top
            or left < window.left or top < window.top or right > window.right or bottom > window.bottom):
        raise RuntimeError("The complete CAPTCHA must be visible inside Chrome")
    controls = [control for control in nodes(region) if not control.IsOffscreen and control.IsEnabled]
    for control in controls:
        if (control.ControlTypeName == "EditControl" and (control.IsPassword or re.search(
                r"\b(e-?mail|phone|address|name|password|login|username)\b", control.Name.casefold()))
                or control.ControlTypeName in {"ButtonControl", "HyperlinkControl"} and re.search(
                    r"register|sign.?up|create.*account|place.*order|checkout|payment", control.Name.casefold())):
            raise RuntimeError("The CAPTCHA region includes account controls; nothing was captured")
    if not region.CaptureToImage(str(path)):
        raise RuntimeError("Could not capture the visible CAPTCHA")
    descriptions = [{"name": control.Name, "role": control.ControlTypeName}
                    for control in controls]
    return (left, top, right, bottom), controls, descriptions


def solve_chrome_captcha(address):
    origin = site_origin(address)
    browser, _ = chrome_password_suggestion(origin)
    if browser is None:
        raise RuntimeError("The requested Chrome page is not available")
    api = automation()
    browser.SetActive(waitTime=.1)
    deadline = time.monotonic() + 90
    with tempfile.TemporaryDirectory(prefix="zenshin-captcha-") as directory:
        image = Path(directory) / "challenge.png"
        for _ in range(12):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            current_browser, _ = chrome_password_suggestion(origin)
            if not api.ControlsAreSame(browser, current_browser):
                raise RuntimeError("Chrome's site changed; CAPTCHA action stopped")
            region = chrome_captcha_region(browser, origin)
            bounds, controls, descriptions = chrome_captcha_snapshot(browser, region, image)
            pixels = image.read_bytes()
            step = ai_decision.captcha_step(image, descriptions, bounds[2] - bounds[0],
                                            bounds[3] - bounds[1], remaining)
            # A CLI round trip can take time. Never use coordinates from an old
            # image, another page, or an overlay that has taken keyboard focus.
            prepare_chrome_site(address, open_site=False)
            current_browser, _ = chrome_password_suggestion(origin)
            if (time.monotonic() >= deadline or not api.ControlsAreSame(browser, current_browser)
                    or not api.ControlsAreSame(region, chrome_captcha_region(browser, origin))):
                raise RuntimeError("Chrome's CAPTCHA changed during analysis; action stopped")
            fresh_bounds, fresh_controls, _ = chrome_captcha_snapshot(browser, region, image)
            if step["action"] == "wait":
                time.sleep(.5)
                continue
            if step["action"] == "verified":
                time.sleep(.3)
                if not api.ControlsAreSame(browser, chrome_password_suggestion(origin)[0]):
                    raise RuntimeError("Chrome's site changed before CAPTCHA confirmation")
                stable_bounds, stable_controls, _ = chrome_captcha_snapshot(browser, region, image)
                checked = any(control.ControlTypeName == "CheckBoxControl"
                              and re.search(r"captcha|human|not a robot", control.Name.casefold())
                              and (toggle := control.GetPattern(api.PatternId.TogglePattern))
                              and toggle.ToggleState == 1 for control in stable_controls)
                if stable_bounds == bounds and (checked or image.read_bytes() == pixels):
                    return {"message": "The CAPTCHA widget visibly confirmed successful verification."}
                continue
            if fresh_bounds != bounds or image.read_bytes() != pixels:
                continue
            if step["action"] == "type":
                field = controls[step["control"]]
                if (field.ControlTypeName != "EditControl" or field.IsPassword
                        or not any(api.ControlsAreSame(field, control) for control in fresh_controls)):
                    raise RuntimeError("The CAPTCHA answer field changed; nothing was entered")
                value = field.GetPattern(api.PatternId.ValuePattern)
                if not value or value.IsReadOnly:
                    raise RuntimeError("The CAPTCHA answer field does not support text entry")
                value.SetValue(step["text"])
            else:
                for x, y in step["points"]:
                    current_browser, _ = chrome_password_suggestion(origin)
                    if (not api.ControlsAreSame(browser, current_browser)
                            or not api.ControlsAreSame(api.GetForegroundControl(), browser)):
                        raise RuntimeError("Chrome changed before a CAPTCHA click; action stopped")
                    rectangle = region.BoundingRectangle
                    if (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom) != bounds:
                        break  # Reobserve a layout change before the next click.
                    hit = api.ControlFromPoint(bounds[0] + x, bounds[1] + y)
                    if not any(api.ControlsAreSame(hit, control) for control in nodes(region)):
                        raise RuntimeError("The CAPTCHA click target is no longer inside the challenge")
                    api.Click(bounds[0] + x, bounds[1] + y, waitTime=.2)
            time.sleep(.5)
    raise RuntimeError("CAPTCHA verification was not confirmed within 90 seconds or 12 steps; do not retry this action")


def entry_text(entry):
    api = automation()
    value = entry.GetPattern(api.PatternId.ValuePattern)
    if value:
        content = value.Value
    else:
        text = entry.GetPattern(api.PatternId.TextPattern)
        if not text:
            raise RuntimeError("Cannot read the desktop input; inspect its draft manually")
        content = text.DocumentRange.GetText(-1)
    # Chromium includes its noneditable placeholder in Value/TextPattern.
    placeholder = any(node.ControlTypeName == "TextControl" and node.Name == entry.Name
                      and "readonly=true" in node.GetParentControl().GetPropertyValue(api.PropertyId.AriaPropertiesProperty)
                      for node in nodes(entry))
    if placeholder and content.strip() == entry.Name:
        return ""
    return content.removesuffix("\n")


def write_text(name, entry, response):
    if entry_text(entry).strip():
        raise RuntimeError("The input already contains a draft; answer it manually")
    value = entry.GetPattern(automation().PatternId.ValuePattern)
    if not value or value.IsReadOnly:
        raise RuntimeError("The desktop input does not expose writable text")
    value.SetValue(response)


def answer(name, question, response, next_question=None, on_progress=None):
    doc = document(name)
    root, expanded = card(doc, question)
    if root is None:
        raise RuntimeError("The selected question is no longer pending in the visible chat")
    if not expanded:
        buttons = matching(root, "ButtonControl", "Answer question")
        if len(buttons) != 1:
            raise RuntimeError("Cannot identify the question's answer button")
        press(buttons[0])
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        doc = document(name)
        root, expanded = card(doc, question)
        if expanded:
            break
        time.sleep(.1)
    if not expanded:
        raise RuntimeError("The question form did not open")
    doc = document(name)
    root, expanded = card(doc, question)
    if not expanded:
        raise RuntimeError("The question changed before submission")
    prior = len(matching(doc, "TextControl", response)) - len(matching(root, "TextControl", response))
    options = matching(root, "RadioButtonControl", response)
    if len(options) == 1:
        press(options[0])
    else:
        entries = answer_entries(root)
        if len(entries) != 1 or entry_text(entries[0]).strip():
            raise RuntimeError("The custom answer already contains a draft; answer it manually")
        write_text(name, entries[0], response)
        doc = document(name)
        root, expanded = card(doc, question)
        entries = answer_entries(root)
        buttons = matching(root, "ButtonControl", "Next" if next_question else "Send")
        if not expanded or len(entries) != 1 or len(buttons) != 1 or entry_text(entries[0]) != response:
            raise RuntimeError("The custom answer changed before Send; inspect its draft manually")
        press(buttons[0])
    if on_progress:
        on_progress("confirming")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        doc = document(name)
        if doc is None:
            raise RuntimeError("The chat changed during delivery; verify it manually")
        if next_question and card(doc, next_question)[0] is not None:
            return
        if not next_question and card(doc, question)[0] is None and len(matching(doc, "TextControl", response)) > prior:
            return
        time.sleep(.2)
    raise RuntimeError("Delivery was not confirmed; inspect the chat before taking further action")


def message_matches(doc, text):
    matches = matching(doc, "TextControl", text)
    expected = " ".join(text.split())
    for group in nodes(doc):
        if group.ControlTypeName != "GroupControl":
            continue
        if not any(child.ControlTypeName == "TextControl" for child in group.GetChildren()):
            continue
        fragments = [child.Name for child in nodes(group) if child.ControlTypeName == "TextControl"]
        if len(fragments) > 1 and " ".join("".join(fragments).split()) == expected:
            matches.append(group)
    return matches


def _chat_setup_pending(name, text):
    doc = document(name)
    return bool(doc and (not text or any(not control.IsOffscreen for control in message_matches(doc, text)))
                and not matching(doc, "ButtonControl", "Stop")
                and not matching(doc, "ButtonControl", "Answer question")
                and not answer_entries(doc)
                and not matching(doc, "ButtonControl", "Allow once"))


def conversation_pending(name, text):
    return bool(text and _chat_setup_pending(name, text))


def chat_setup_ready(name, text):
    if not _chat_setup_pending(name, text):
        return False
    entries = matching(document(name), "EditControl", "Work with Codex")
    return bool(len(entries) == 1 and entries[0].IsEnabled and not entries[0].IsOffscreen
                and not entry_text(entries[0]).strip())


def reply(name, text, response, on_progress=None):
    _send_reply(name, text, response, conversation_pending, on_progress)


def send_chat_setup(name, text, response, on_progress=None):
    return _send_reply(name, text, response, _chat_setup_pending, on_progress, defer=True)


def _send_reply(name, text, response, is_pending, on_progress, defer=False):
    if not is_pending(name, text):
        if defer:
            return False
        raise RuntimeError("The chat is running or its latest message is not visible")
    doc = document(name)
    entries = matching(doc, "EditControl", "Work with Codex")
    if (len(entries) != 1 or not entries[0].IsEnabled or entries[0].IsOffscreen
            or entry_text(entries[0]).strip()):
        if defer:
            return False
        raise RuntimeError("The composer contains a draft; reply manually")
    prior = len(message_matches(doc, response))
    write_text(name, entries[0], response)
    doc = document(name)
    entries = matching(doc, "EditControl", "Work with Codex")
    buttons = matching(entries[0].GetParentControl(), "ButtonControl", "Send") if len(entries) == 1 else []
    if not is_pending(name, text) or len(entries) != 1 or entry_text(entries[0]) != response or len(buttons) != 1:
        raise RuntimeError("Composer changed before Send; inspect its draft manually")
    press(buttons[0])
    if on_progress:
        on_progress("confirming")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        doc = document(name)
        if doc is None:
            break
        if len(message_matches(doc, response)) > prior:
            return True
        time.sleep(.2)
    raise RuntimeError("Reply delivery was not confirmed; inspect the chat manually")


def approval_forms(name):
    forms = []
    for button in matching(document(name), "ButtonControl", "Allow once"):
        root = button.GetParentControl()
        while root and root.ControlTypeName != "DocumentControl":
            if matching(root, "EditControl", "Work with Codex"):
                break
            # Walk past the button row to include the actual requested access.
            context = (matching(root, "TextControl", "Permissions") or
                       any(node.GetPropertyValue(automation().PropertyId.AriaRoleProperty) == "alert" for node in nodes(root)))
            if context and len(matching(root, "ButtonControl", "Deny")) == 1:
                text = "\n".join(node.Name for node in nodes(root) if node.ControlTypeName == "TextControl")
                if text.strip():
                    forms.append({"text": text, "button": button})
                break
            root = root.GetParentControl()
    return forms


def approval_cards(name):
    return [{"text": form["text"], "options": ["Allow once"]} for form in approval_forms(name)]


def approve(name, text, response, on_progress=None):
    if response != "Allow once":
        raise RuntimeError("Approval dialogs only support the one-time Allow once action")
    forms = [form for form in approval_forms(name) if form["text"] == text]
    if len(forms) != 1:
        raise RuntimeError("The approval card changed or is ambiguous; inspect it manually")
    press(forms[0]["button"])
    if on_progress:
        on_progress("confirming")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if document(name) is None:
            raise RuntimeError("The chat changed during approval; inspect it manually")
        if not any(card["text"] == text for card in approval_cards(name)):
            return
        time.sleep(.2)
    raise RuntimeError("Approval was not confirmed; inspect the request manually")
