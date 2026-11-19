"""View a native Windows test machine's own RDP desktop in FreeRDP.

Windows owns its RDP listener and autologon session, so there is no SSH run,
XFCE display or geometry probe: the viewer connects to the registered
listener and lets the remote desktop follow the window size. Signing in as
the autologon user disconnects the console; the host's
YokeQa-ReturnToConsole task returns it when the viewer closes.
"""

from __future__ import annotations

from yoke_harness.rdp_desktop_client import DesktopView, watch_view

DISPLAY_OPTIONS = ("/dynamic-resolution",)
SESSION = {"desktop_session": "native"}


def open_native_view(project, test_machine, settings, password):
    """Start the viewer and leave it open until close()."""
    return DesktopView.start(
        project, test_machine, settings, password, list(DISPLAY_OPTIONS), dict(SESSION)
    )


def view_native_desktop(project, test_machine, settings, password):
    """Open the viewer and report its outcome once it closes."""
    return watch_view(open_native_view(project, test_machine, settings, password))
