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


