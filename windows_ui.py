"""Named Windows UI Automation controls for the native Codex desktop app."""

from contextlib import contextmanager
import ctypes
import os
import time
from urllib.parse import quote


def automation():
    try:
        import uiautomation
    except ImportError as error:
        raise RuntimeError("Windows desktop access needs: python -m pip install -r requirements-windows.txt") from error
    return uiautomation


@contextmanager
def session():
    # HTTP operations run on different threads; controls stay in their own poll.
    api = automation()
    with api.UIAutomationInitializerInThread():
        try:
            yield
        except api.comtypes.COMError as error:
            raise RuntimeError("Windows desktop controls became unavailable; inspect the chat manually") from error


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
    if document(name) is not None:
        return
    if on_open:
        on_open()
    try:
        os.startfile("codex://threads/" + quote(thread_id, safe=""))
    except OSError as error:
        raise RuntimeError("Could not open the selected chat in Codex: " + str(error)) from error
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if document(name) is not None:
            return
        time.sleep(.25)
    raise RuntimeError("The selected chat did not appear in Codex; check accessibility and open it manually")


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


def conversation_pending(name, text):
    doc = document(name)
    return bool(doc and matching(doc, "TextControl", text)
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
    prior = len(matching(doc, "TextControl", response))
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
        if len(matching(doc, "TextControl", response)) > prior:
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
