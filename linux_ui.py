"""Normal Linux accessibility controls for Codex's question cards."""

import time


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


def matching(root, role, name):
    return [node for node in nodes(root)
            if node.get_role_name() == role and node.get_name() == name]


def card(doc, question):
    # The expanded request card is separate from the ordinary message composer.
    forms = matching(doc, "entry", "Or write your own response")
    for entry in forms:
        parent = entry.get_parent()
        if matching(parent, "static", question) and matching(parent, "push button", "Send"):
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


