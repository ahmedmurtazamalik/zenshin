"""Named Windows UI Automation controls for the native Codex desktop app."""

from concurrent.futures import ThreadPoolExecutor
import ctypes
import os
import re
import subprocess
import time
from urllib.parse import quote, urlsplit


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


def chrome_password_suggestion(origin):
    matches, browsers = [], []
    api = automation()
    for window in api.GetRootControl().GetChildren():
        if window.IsOffscreen or not process_path(window.ProcessId).lower().endswith("\\chrome.exe"):
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
        browser, _ = chrome_password_suggestion(origin)
        native = list(nodes(browser, stop_at_documents=True)) if browser else []
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
                return {"message": f"Chrome is on {origin} and has finished loading. You can start a fresh computer-use attempt."}
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


def accept_chrome_password(address):
    origin = site_origin(address.strip())
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        browser, suggestion = chrome_password_suggestion(origin)
        if suggestion is not None:
            # Re-read the site and native popup immediately before activation.
            current_browser, current = chrome_password_suggestion(origin)
            api = automation()
            if (current is None or not api.ControlsAreSame(browser, current_browser)
                    or not api.ControlsAreSame(suggestion, current)):
                raise RuntimeError("Chrome's password suggestion changed; nothing was selected")
            press(current)  # Exactly one activation; never retry an uncertain result.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                current_browser, remaining = chrome_password_suggestion(origin)
                if current_browser is None or not api.ControlsAreSame(browser, current_browser):
                    raise RuntimeError("Chrome's site changed after activation; inspect Chrome before trying again")
                if remaining is None:
                    return {"message": "Chrome's password suggestion was activated and closed. Check the filled fields before continuing."}
                time.sleep(.2)
            raise RuntimeError("Chrome's suggestion did not close after activation; inspect Chrome before trying again")
        time.sleep(.2)
    raise RuntimeError("No supported Chrome password suggestion appeared for this site within 30 seconds; nothing was selected")


def chrome_signup_request(origin, password=False, terms=False):
    browser, suggestion = chrome_password_suggestion(origin)
    if password and suggestion is not None:
        return {"kind": "password", "label": "Chrome suggested password"}
    if not terms or browser is None:
        return None
    matches = []
    api = automation()
    for doc in nodes(browser, stop_at_documents=True):
        if doc.ControlTypeName != "DocumentControl" or doc.IsOffscreen:
            continue
        value = doc.GetPattern(api.PatternId.ValuePattern)
        if not value or not value.Value.startswith(origin + "/"):
            continue
        for control in nodes(doc):
            if control.ControlTypeName != "CheckBoxControl" or control.IsOffscreen or not control.IsEnabled:
                continue
            label = control.Name
            if (not re.search(r"\b(?:agree|accept)\b.*\bterms\b|\bterms (?:and|&) conditions\b|\bterms of (?:service|use)\b", label, re.I)
                    or re.search(r"marketing|newsletter|promotional|offers|updates|subscrib|partners", label, re.I)):
                continue
            toggle = control.GetPattern(api.PatternId.TogglePattern)
            if toggle and toggle.ToggleState == 0:
                matches.append({"kind": "terms", "label": label})
    if len(matches) > 1:
        raise RuntimeError("Several terms checkboxes are available; inspect the form manually")
    return matches[0] if matches else None


def perform_chrome_signup_request(origin, request):
    current = chrome_signup_request(origin, password=request["kind"] == "password",
                                    terms=request["kind"] == "terms")
    if current != request:
        raise RuntimeError("Chrome's signup control changed; nothing was selected")
    if request["kind"] == "password":
        return accept_chrome_password(origin)
    browser, _ = chrome_password_suggestion(origin)
    controls = [control for control in nodes(browser) if control.ControlTypeName == "CheckBoxControl"
                and control.Name == request["label"] and not control.IsOffscreen and control.IsEnabled]
    if len(controls) != 1:
        raise RuntimeError("The terms checkbox changed or is ambiguous; inspect Chrome manually")
    toggle = controls[0].GetPattern(automation().PatternId.TogglePattern)
    if not toggle or toggle.ToggleState != 0:
        raise RuntimeError("The terms checkbox changed; nothing was selected")
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


def conversation_pending(name, text):
    doc = document(name)
    return bool(doc and any(not control.IsOffscreen for control in message_matches(doc, text))
                and not matching(doc, "ButtonControl", "Stop")
                and not matching(doc, "ButtonControl", "Answer question")
                and not answer_entries(doc)
                and not matching(doc, "ButtonControl", "Allow once"))


def reply(name, text, response, on_progress=None):
    if not conversation_pending(name, text):
        raise RuntimeError("The chat is running or its latest message is not visible")
    doc = document(name)
    entries = matching(doc, "EditControl", "Work with Codex")
    if len(entries) != 1 or entry_text(entries[0]).strip():
        raise RuntimeError("The composer contains a draft; reply manually")
    prior = len(message_matches(doc, response))
    write_text(name, entries[0], response)
    doc = document(name)
    entries = matching(doc, "EditControl", "Work with Codex")
    buttons = matching(entries[0].GetParentControl(), "ButtonControl", "Send") if len(entries) == 1 else []
    if not conversation_pending(name, text) or len(entries) != 1 or entry_text(entries[0]) != response or len(buttons) != 1:
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
            return
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
