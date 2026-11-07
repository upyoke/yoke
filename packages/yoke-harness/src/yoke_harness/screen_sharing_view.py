"""Open macOS Screen Sharing on a Mac test machine's VNC route.

The password never enters argv, the URL or logs: it goes to the clipboard on
pbcopy's stdin and leaves it after CLIPBOARD_SECONDS, unless replaced first.
"""

from __future__ import annotations

from contextlib import ExitStack
import subprocess
import sys
import threading
from urllib.parse import quote

from yoke_harness.desktop_access import DesktopAccessError
from yoke_harness.desktop_forward import desktop_forward

CLIPBOARD_SECONDS = 60
CLIPBOARD_RECOVERY = "copy any other text to replace the desktop password on the clipboard"


def _clipboard_holds(password: str) -> bool:
    held = subprocess.run(
        ["pbpaste"], capture_output=True, text=True, timeout=5, check=True
    )
    return held.stdout == password


def _copy(text: str) -> None:
    subprocess.run(
        ["pbcopy"], input=text, text=True, capture_output=True, timeout=5, check=True
    )


class ScreenSharingView:
    """One Screen Sharing launch. Close clears the clipboard and any SSH forward."""

    def __init__(self, stack, password, address, user):
        self._stack = stack
        self._password = password
        self._lock = threading.Lock()
        self._clipboard_owned = True
        self.address = address
        self.user = user
        self._timer = threading.Timer(CLIPBOARD_SECONDS, self._expire)
        self._timer.daemon = True

    @classmethod
    def open(cls, project, test_machine, settings, password):
        if sys.platform != "darwin":
            raise DesktopAccessError(
                "desktop_view_requires_mac_workstation: Screen Sharing opens only on macOS; "
                "run yoke test-machine desktop-access without --view and connect a VNC "
                "client to the printed address as the printed user, with the password "
                "in password_file"
            )
        stack = ExitStack()
        try:
            host, port, user = stack.enter_context(desktop_forward(project, settings))
            authority = f"[{host}]" if ":" in host else host
            address = f"vnc://{quote(user, safe='')}@{authority}:{port}"
            view = cls(stack, password, address, user)
            try:
                _copy(password)
            except (OSError, subprocess.SubprocessError):
                raise DesktopAccessError(
                    "desktop_clipboard_unavailable: pbcopy failed; run yoke test-machine "
                    "desktop-access without --view and read the printed password_file"
                ) from None
            try:
                opened = subprocess.run(
                    ["open", address], capture_output=True, timeout=20, check=False
                )
            except (OSError, subprocess.TimeoutExpired):
                opened = None
            if opened is None or opened.returncode:
                view.close()
                raise DesktopAccessError(
                    f"desktop_view_open_failed: macOS could not open {address}; open "
                    "Screen Sharing once from Spotlight so it handles vnc:// links, then "
                    "rerun desktop-access --view"
                )
            view._timer.start()
            print(
                f"Screen Sharing is opening {address} for test machine {test_machine}. "
                f"Paste the desktop password from the clipboard at its prompt; Yoke "
                f"clears it in {CLIPBOARD_SECONDS} seconds. Clipboard-history apps "
                "may keep a copy.",
                file=sys.stderr,
                flush=True,
            )
            return view
        except BaseException:
            stack.close()
            raise

    closing = "quit Screen Sharing after verification finishes."

    def describe(self, test_machine):
        return (
            f"Screen Sharing opens {self.address}; paste the desktop password "
            "from the clipboard."
        )

    def _clear_clipboard(self):
        """Clear only the password Yoke placed; a later copy belongs to the operator."""
        with self._lock:
            if not self._clipboard_owned:
                return
            try:
                if _clipboard_holds(self._password):
                    _copy("")
            except (OSError, subprocess.SubprocessError):
                raise DesktopAccessError(
                    f"desktop_clipboard_clear_failed: {CLIPBOARD_RECOVERY}"
                ) from None
            self._clipboard_owned = False

    def _expire(self):
        try:
            self._clear_clipboard()
        except DesktopAccessError as exc:
            print(f"error: {exc}", file=sys.stderr, flush=True)

    def wait_for_clipboard(self):
        if self._timer.is_alive():
            self._timer.join()

    def close(self):
        self._timer.cancel()
        try:
            self._clear_clipboard()
        finally:
            self._stack.close()


def view_screen_sharing(project, test_machine, settings, password):
    """Hold any forward until Enter; without a terminal, until the clipboard clears."""
    view = ScreenSharingView.open(project, test_machine, settings, password)
    try:
        print(
            "Press Enter here when you are done to close the desktop route.",
            file=sys.stderr,
            flush=True,
        )
        try:
            if not sys.stdin.readline():
                view.wait_for_clipboard()
        except KeyboardInterrupt:
            pass
    finally:
        view.close()
    return {"address": view.address, "user": view.user, "viewer": "closed"}
