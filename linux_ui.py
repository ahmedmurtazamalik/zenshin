"""Normal Linux accessibility controls for Codex's question cards."""

import subprocess
import time
from urllib.parse import quote


def atspi():
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except (ImportError, ValueError) as error:
        raise RuntimeError("Desktop access requires the system Python gi/AT-SPI package") from error
    Atspi.set_timeout(1000, 1000)
    return Atspi


def nodes(node, stop_at_documents=False):
    if node is None:
        return
    # Navigation contains other conversations, never permission controls.
    if node.get_role_name() == "landmark" and node.get_name() in {"Home", "App navigation"}:
        return
    yield node
    if stop_at_documents and node.get_role_name() == "document web":
        return
    for index in range(max(0, node.get_child_count())):
        yield from nodes(node.get_child_at_index(index), stop_at_documents)


def document(name):
    api = atspi()
    desktop = api.get_desktop(0)
    matches = []
    for index in range(desktop.get_child_count()):
        application = desktop.get_child_at_index(index)
        if application is None or application.get_name() != "Codex":
            continue
        # Chromium's cached tree can contain null children; read fresh controls.
        application.set_cache_mask(api.Cache.NONE)
        matches.extend(node for node in nodes(application, stop_at_documents=True)
                       if node.get_role_name() == "document web" and node.get_name() == name)
    if len(matches) > 1:
        raise RuntimeError("This chat is open in multiple desktop windows; leave only one open")
    return matches[0] if matches else None


def open_chat(thread_id, name, on_open=None):
    if document(name) is not None:
        return
    if on_open:
        on_open()
    try:
        subprocess.run(["xdg-open", "codex://threads/" + quote(thread_id, safe="")],
                       check=True, timeout=5, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("Could not open the selected chat in Codex: " + str(error)) from error
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if document(name) is not None:
            return
        time.sleep(.25)
    raise RuntimeError("The selected chat did not appear in Codex; check desktop accessibility, open it manually, and restart monitoring")


def matching(root, role, name):
    return [node for node in nodes(root)
            if node.get_role_name() == role and node.get_name() == name]


def answer_entries(root):
    return matching(root, "entry", "Or write your own response") + matching(root, "entry", "Reply…")


def card(doc, question):
    # The expanded request card is separate from the ordinary message composer.
    forms = answer_entries(doc)
    for entry in forms:
        parent = entry.get_parent()
        if matching(parent, "static", question) and (matching(parent, "push button", "Send") or matching(parent, "push button", "Next")):
            return parent, True
    closed = []
    for button in matching(doc, "push button", "Answer question"):
        parent = button.get_parent()
        if matching(parent, "static", question):
            closed.append(parent)
    if len(closed) > 1:
        raise RuntimeError("Several pending cards have the same question; answer them manually")
    return (closed[0], False) if closed else (None, False)


def pending(name, question):
    doc = document(name)
    if doc is None:
        return False
    return card(doc, question)[0] is not None


def press(button):
    for index in range(button.get_n_actions()):
        if button.get_action_name(index) in {"press", "click", "check", "open", "select"}:
            if button.do_action(index):
                return
            break
    raise RuntimeError("The desktop control did not accept the action")


def entry_text(entry):
    text = atspi().Text.get_text(entry, 0, -1)
    if "\ufffc" not in text:
        return text
    # Chromium contenteditable exposes paragraphs as embedded objects. Its
    # placeholder is a section; actual text is rendered separately.
    return "".join(node.get_name() for node in nodes(entry)
                   if node.get_role_name() == "static"
                   and not (node.get_name() == entry.get_name()
                            and node.get_parent().get_role_name() == "section"))


def write_text(name, entry, response):
    api = atspi()
    if api.EditableText.set_text_contents(entry, response):
        return
    # Wayland Chromium rejects EditableText. Use a short GNOME keyboard session
    # only while the selected empty field retains focus, then verify readback.
    if "\n" in response:
        raise RuntimeError("Desktop keyboard fallback supports single-line replies")
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    destination = "org.gnome.Mutter.RemoteDesktop"
    path = bus.call_sync(destination, "/org/gnome/Mutter/RemoteDesktop", destination,
                         "CreateSession", None, None, 0, 3000, None).unpack()[0]
    def call(method, args=None):
        return bus.call_sync(destination, path, destination + ".Session", method,
                             args, None, 0, 3000, None)
    call("Start")
    try:
        if not entry.grab_focus():
            raise RuntimeError("Cannot focus the answer field")
        time.sleep(0.1)
        for character in response:
            if document(name) is None or not entry.get_state_set().contains(api.StateType.FOCUSED):
                raise RuntimeError("The chat or text focus changed; inspect the draft manually")
            keysym = ord(character)
            if keysym > 127:
                keysym |= 0x01000000
            for pressed in (True, False):
                call("NotifyKeyboardKeysym", GLib.Variant("(ub)", (keysym, pressed)))
    finally:
        call("Stop")


def answer(name, question, response, next_question=None, on_progress=None):
    doc = document(name)
    root, expanded = card(doc, question)
    if root is None:
        raise RuntimeError("The selected question is no longer pending in the visible chat")
    if not expanded:
        buttons = matching(root, "push button", "Answer question")
        if len(buttons) != 1:
            raise RuntimeError("Cannot identify the question's answer button")
        press(buttons[0])
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        doc = document(name)
        root, expanded = card(doc, question)
        if expanded:
            break
        time.sleep(0.1)
    if not expanded:
        raise RuntimeError("The question form did not open")
    # Offered choices submit immediately; custom text uses the separate Send.
    doc = document(name)
    root, expanded = card(doc, question)
    options = matching(root, "radio button", response)
    api = atspi()
    if not expanded:
        raise RuntimeError("The question changed before submission")
    prior_echoes = len(matching(doc, "static", response)) - len(matching(root, "static", response))
    if len(options) == 1:
        if not options[0].get_state_set().contains(api.StateType.ENABLED):
            raise RuntimeError("The offered response is disabled")
        press(options[0])
    else:
        entries = answer_entries(root)
        if len(entries) != 1 or entry_text(entries[0]).strip():
            raise RuntimeError("The custom answer already contains a draft; answer it manually")
        write_text(name, entries[0], response)
        # Read back the live form immediately before sending. Never
        # overwrite an existing user draft.
        doc = document(name)
        root, expanded = card(doc, question)
        entries = answer_entries(root)
        buttons = matching(root, "push button", "Next" if next_question else "Send")
        if (not expanded or len(entries) != 1 or len(buttons) != 1
                or entry_text(entries[0]) != response
                or not buttons[0].get_state_set().contains(api.StateType.ENABLED)):
            raise RuntimeError("The custom answer changed before Send; inspect its draft manually")
        press(buttons[0])
    # A closed card alone could mean navigation or dismissal. Require an echoed
    # answer in the same chat as well before reporting delivery.
    if on_progress:
        on_progress("confirming")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        doc = document(name)
        if doc is None:
            raise RuntimeError("The chat changed during delivery; verify it manually")
        if next_question and card(doc, next_question)[0] is not None:
            return
        if not next_question and card(doc, question)[0] is None and len(matching(doc, "static", response)) > prior_echoes:
            return
        time.sleep(0.2)
    raise RuntimeError("Delivery was not confirmed; inspect the chat before taking further action")


def conversation_pending(name, text):
    doc = document(name)
    return bool(doc and matching(doc, "static", text)
                and not matching(doc, "push button", "Stop")
                and not matching(doc, "push button", "Answer question")
                and not answer_entries(doc)
                and not matching(doc, "push button", "Allow once"))


def reply(name, text, response, on_progress=None):
    if not conversation_pending(name, text):
        raise RuntimeError("The chat is running or its latest message is not visible")
    doc = document(name)
    entries = matching(doc, "entry", "Work with Codex")
    if len(entries) != 1 or entry_text(entries[0]).strip():
        raise RuntimeError("The composer contains a draft; reply manually")
    prior = len(matching(doc, "static", response))
    write_text(name, entries[0], response)
    doc = document(name)
    entries = matching(doc, "entry", "Work with Codex")
    buttons = matching(entries[0].get_parent(), "push button", "Send") if len(entries) == 1 else []
    if (not conversation_pending(name, text) or len(entries) != 1
            or entry_text(entries[0]) != response or len(buttons) != 1
            or not buttons[0].get_state_set().contains(atspi().StateType.ENABLED)):
        raise RuntimeError("Composer changed before Send; inspect its draft manually")
    press(buttons[0])
    if on_progress:
        on_progress("confirming")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        doc = document(name)
        if doc is None:
            break
        if len(matching(doc, "static", response)) > prior:
            return
        time.sleep(0.2)
    raise RuntimeError("Reply delivery was not confirmed; inspect the chat manually")


def approval_forms(name):
    doc = document(name)
    if doc is None:
        return []
    forms = []
    for button in matching(doc, "push button", "Allow once"):
        root = button.get_parent()
        # Command cards have an alert; file-access cards have a Permissions heading.
        while root and root.get_role_name() != "document web":
            if matching(root, "entry", "Work with Codex"):
                break
            if (any(node.get_role_name() == "alert" for node in nodes(root))
                    or matching(root, "static", "Permissions")):
                if len(matching(root, "push button", "Deny")) != 1:
                    break
                text = "\n".join(node.get_name() for node in nodes(root)
                                 if node.get_role_name() == "static")
                if text.strip():
                    forms.append({"text": text, "button": button})
                break
            root = root.get_parent()
    return forms


def approval_cards(name):
    return [{"text": form["text"], "options": ["Allow once"]} for form in approval_forms(name)]


def approve(name, text, response, on_progress=None):
    if response != "Allow once":
        raise RuntimeError("Approval dialogs only support the one-time Allow once action")
    forms = [form for form in approval_forms(name) if form["text"] == text]
    if len(forms) != 1:
        raise RuntimeError("The approval card changed or is ambiguous; inspect it manually")
    button = forms[0]["button"]
    if not button.get_state_set().contains(atspi().StateType.ENABLED):
        raise RuntimeError("The approval action is disabled")
    press(button)
    if on_progress:
        on_progress("confirming")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if document(name) is None:
            raise RuntimeError("The chat changed during approval; inspect it manually")
        if not any(card["text"] == text for card in approval_cards(name)):
            return
        time.sleep(0.2)
    raise RuntimeError("Approval was not confirmed; inspect the request manually")
