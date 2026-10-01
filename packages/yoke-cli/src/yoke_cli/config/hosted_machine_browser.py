"""Hand the hosted approval URL to a browser and say what happened.

``webbrowser.open`` can report failure inside a full-screen terminal app
without saying why; every attempt here is recorded so the wizard's log and
its waiting view can name the reason, and macOS/WSL get native browser commands as
a second route.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import platform as platform_info
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Callable, Mapping
import webbrowser

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.hosted_machine_authorization import PendingMachineAuthorization


@dataclass(frozen=True)
class BrowserOpenResult:
    """What happened when the approval URL was handed to a browser.

    ``method`` names the opener that succeeded (``webbrowser``, ``open``,
    ``wslview`` or ``explorer.exe``); ``reason`` carries every failed attempt in order so the
    diagnostic log and the waiting view can say why nothing opened.
    """

    opened: bool
    method: str | None = None
    reason: str | None = None


# The macOS ``open`` command hands a URL to the default browser without the
# ``webbrowser`` module's controller probing, which can fail inside a full-screen
# terminal app without reporting why.
MACOS_PLATFORM = "darwin"
_BROWSER_OPEN_TIMEOUT_SECONDS = 10.0


def open_browser(
    authorization: PendingMachineAuthorization,
    *,
    browser_open: Callable[[str], Any] | None = None,
    macos_open: Callable[[str], subprocess.CompletedProcess[str]] | None = None,
    platform: str = sys.platform,
) -> BrowserOpenResult:
    """Open the complete approval URL, recording why each attempt failed.

    The complete URL carries the one-time code, so it is the one to open; the
    bare sign-in page would ask for the code again.
    """
    return open_url(
        authorization.verification_uri_complete,
        browser_open=browser_open,
        macos_open=macos_open,
        platform=platform,
    )


def open_url(
    url: str,
    *,
    browser_open: Callable[[str], Any] | None = None,
    macos_open: Callable[[str], subprocess.CompletedProcess[str]] | None = None,
    platform: str = sys.platform,
    environ: Mapping[str, str] | None = None,
) -> BrowserOpenResult:
    """Hand *url* to a browser, recording why each attempt failed.

    ``webbrowser.open`` goes first. macOS then tries ``open``; WSL tries
    ``wslview`` and ``explorer.exe`` to reach the Windows browser. Every
    failed attempt is retained for the caller's diagnostics.
    """
    attempts: list[str] = []
    try:
        if bool((browser_open or webbrowser.open)(url)):
            return BrowserOpenResult(opened=True, method="webbrowser")
        attempts.append("webbrowser.open returned False")
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, not raised
        attempts.append(f"webbrowser.open raised {type(exc).__name__}: {exc}")
    env = os.environ if environ is None else environ
    if platform == "linux" and (
        env.get("WSL_DISTRO_NAME")
        or env.get("WSL_INTEROP")
        or "microsoft" in platform_info.release().lower()
    ):
        for executable in ("wslview", "explorer.exe"):
            path = shutil.which(executable)
            if path is None:
                attempts.append(f"{executable} unavailable on PATH")
                continue
            try:
                completed = subprocess.run(
                    [path, url],
                    capture_output=True,
                    text=True,
                    timeout=_BROWSER_OPEN_TIMEOUT_SECONDS,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                attempts.append(f"{executable} failed: {type(exc).__name__}: {exc}")
                continue
            if completed.returncode == 0:
                return BrowserOpenResult(
                    opened=True,
                    method=executable,
                    reason="; ".join(attempts),
                )
            attempts.append(
                f"{executable} exited {completed.returncode}: "
                + ((completed.stderr or "").strip() or "no output")
            )
    if platform == MACOS_PLATFORM:
        try:
            completed = (macos_open or _run_macos_open)(url)
        except (OSError, subprocess.SubprocessError) as exc:
            attempts.append(f"open command failed: {type(exc).__name__}: {exc}")
        else:
            if completed.returncode == 0:
                return BrowserOpenResult(
                    opened=True,
                    method="open",
                    reason="; ".join(attempts),
                )
            detail = (completed.stderr or "").strip() or "no output"
            attempts.append(f"open command exited {completed.returncode}: {detail}")
    return BrowserOpenResult(opened=False, reason="; ".join(attempts))


def _run_macos_open(url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["open", url],
        capture_output=True,
        text=True,
        timeout=_BROWSER_OPEN_TIMEOUT_SECONDS,
        check=False,
    )


__all__ = ["BrowserOpenResult", "MACOS_PLATFORM", "open_browser", "open_url"]
