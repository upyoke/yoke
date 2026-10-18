"""Hand the hosted approval URL to a browser and say what happened.

Every attempt here is recorded so the wizard's log and its waiting view can
name the reason. macOS and WSL use native browser commands run without the
terminal: ``webbrowser.open`` starts its POSIX helpers attached to it, where
they could take the wizard's terminal, and can fail without saying why.
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
from yoke_contracts import terminal_detached_process

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
    attempted: bool = True


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

    Linux verifies the default browser or opens QA's shared Chromium runtime.
    macOS runs ``open``; WSL tries ``wslview`` and ``explorer.exe`` to reach
    the Windows browser; other platforms use ``webbrowser.open``. Every
    failed attempt is retained for the caller's diagnostics.

    An injected *browser_open* replaces the whole real chain: its failure is
    the answer, and no native command runs after it. Only an injected
    *macos_open* still runs as the macOS second route, so a caller that fakes
    one opener can never reach the operator's real browser through another.
    """
    env = os.environ if environ is None else environ
    is_wsl = platform == "linux" and (
        env.get("WSL_DISTRO_NAME")
        or env.get("WSL_INTEROP")
        or "microsoft" in platform_info.release().lower()
    )
    if platform == "linux" and not is_wsl and browser_open is None:
        return _open_linux_url(url, env)
    attempts: list[str] = []
    native_fallback = browser_open is None
    if browser_open is not None or not (is_wsl or platform == MACOS_PLATFORM):
        try:
            if bool((browser_open or webbrowser.open)(url)):
                return BrowserOpenResult(opened=True, method="webbrowser")
            attempts.append("webbrowser.open returned False")
        except Exception as exc:  # noqa: BLE001 - every failure is recorded
            attempts.append(f"webbrowser.open raised {type(exc).__name__}: {exc}")
    if is_wsl and native_fallback:
        for executable in ("wslview", "explorer.exe"):
            path = shutil.which(executable)
            if path is None:
                attempts.append(f"{executable} unavailable on PATH")
                continue
            try:
                completed = terminal_detached_process.run(
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
    macos_launch = macos_open or (_run_macos_open if native_fallback else None)
    if platform == MACOS_PLATFORM and macos_launch is not None:
        try:
            completed = macos_launch(url)
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


def _open_linux_url(url: str, env: Mapping[str, str]) -> BrowserOpenResult:
    from yoke_cli.config import onboard_browser_runtime as runtime

    if not runtime.desktop_available(env):
        return BrowserOpenResult(opened=False, reason="browser_display_unavailable")
    attempts: list[str] = []
    try:
        command = runtime.default_browser_command(env)
        if command:
            runtime.open_system_browser(command, url, env)
            return BrowserOpenResult(opened=True, method="system-browser")
        attempts.append("system_browser_unavailable")
    except Exception as exc:  # noqa: BLE001 - link and code remain the recovery
        return BrowserOpenResult(
            opened=False, reason=f"system_browser_open_failed: {exc}"
        )
    try:
        runtime.open_runtime_browser(url)
        return BrowserOpenResult(
            opened=True, method="yoke-chromium", reason="; ".join(attempts)
        )
    except Exception as exc:  # noqa: BLE001 - link and code remain the recovery
        attempts.append(
            f"browser_runtime_open_failed: {exc}; retry yoke qa browser setup"
        )
    return BrowserOpenResult(opened=False, reason="; ".join(attempts))


def _run_macos_open(url: str) -> subprocess.CompletedProcess[str]:
    return terminal_detached_process.run(
        ["open", url],
        capture_output=True,
        text=True,
        timeout=_BROWSER_OPEN_TIMEOUT_SECONDS,
        check=False,
    )


__all__ = ["BrowserOpenResult", "MACOS_PLATFORM", "open_browser", "open_url"]
