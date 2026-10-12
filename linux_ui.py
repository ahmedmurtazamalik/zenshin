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


