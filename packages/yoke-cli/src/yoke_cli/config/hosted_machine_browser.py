"""Hand the hosted approval URL to a browser and say what happened.

``webbrowser.open`` can report failure inside a full-screen terminal app
without saying why; every attempt here is recorded so the wizard's log and
its waiting view can name the reason, and macOS gets the ``open`` command as
a second route.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Callable
import webbrowser

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.hosted_machine_authorization import PendingMachineAuthorization


@dataclass(frozen=True)
class BrowserOpenResult:
    """What happened when the approval URL was handed to a browser.

    ``method`` names the opener that succeeded (``webbrowser`` or the macOS
    ``open`` command); ``reason`` carries every failed attempt in order so the
    diagnostic log and the waiting view can say why nothing opened.
    """

    opened: bool
    method: str | None = None
    reason: str | None = None


# The macOS ``open`` command hands a URL to the default browser without the
# ``webbrowser`` module's controller probing, which can fail inside a full-screen
# terminal app without reporting why.
MACOS_PLATFORM = "darwin"
_MACOS_OPEN_TIMEOUT_SECONDS = 10.0


def open_browser(
    authorization: PendingMachineAuthorization,
    *,
    browser_open: Callable[[str], Any] | None = None,
    macos_open: Callable[[str], subprocess.CompletedProcess[str]] | None = None,
    platform: str = sys.platform,
) -> BrowserOpenResult:
    """Open the complete approval URL, recording why each attempt failed.

    ``webbrowser.open`` goes first; when it reports failure (a false return or
    an exception) on macOS, the ``open`` command is tried next. The visible URL
    in the calling view remains the fallback either way.
    """
    url = authorization.verification_uri_complete
    attempts: list[str] = []
    try:
        if bool((browser_open or webbrowser.open)(url)):
            return BrowserOpenResult(opened=True, method="webbrowser")
        attempts.append("webbrowser.open returned False")
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, not raised
        attempts.append(f"webbrowser.open raised {type(exc).__name__}: {exc}")
    if platform == MACOS_PLATFORM:
        try:
            completed = (macos_open or _run_macos_open)(url)
        except (OSError, subprocess.SubprocessError) as exc:
            attempts.append(f"open command failed: {type(exc).__name__}: {exc}")
        else:
            if completed.returncode == 0:
                return BrowserOpenResult(
                    opened=True, method="open", reason="; ".join(attempts),
                )
            detail = (completed.stderr or "").strip() or "no output"
            attempts.append(f"open command exited {completed.returncode}: {detail}")
    return BrowserOpenResult(opened=False, reason="; ".join(attempts))


def _run_macos_open(url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["open", url],
        capture_output=True,
        text=True,
        timeout=_MACOS_OPEN_TIMEOUT_SECONDS,
        check=False,
    )


__all__ = ["BrowserOpenResult", "MACOS_PLATFORM", "open_browser"]
