"""Browser daemon startup and diagnostics for product browser QA."""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from yoke_harness import browser_client


def _log(message: str) -> None:
    """Write one browser-runtime diagnostic without runner-layer coupling."""
    print(f"[browser-runtime] {message}", file=sys.stderr)


def ensure_daemon_running(project: Optional[str] = None) -> Optional[str]:
    """Ensure the daemon runs on ``project``'s persistent browser profile.

    An authorized profile makes every context the daemon hands out signed into
    whatever the operator signed into; a project with no profile keeps the
    previous clean-context behavior. ``daemon_start`` restarts a daemon that
    is live on a different project's profile rather than reusing it.
    """
    from yoke_cli.config.browser_profile import resolve_authorized_profile

    profile_path, profile_note = resolve_authorized_profile(project)
    _log(profile_note)
    profile = str(profile_path) if profile_path else None

    state = browser_client.DaemonState.load()
    if (
        state
        and browser_client.daemon_running(state)
        and state.profile_dir == (profile or "")
    ):
        try:
            browser_client.daemon_health(state=state, timeout=1)
        except RuntimeError as exc:
            _log(
                "Browser daemon process is alive but not ready; "
                f"recovering endpoint={state.endpoint} pid={state.pid}: {exc}"
            )
            try:
                browser_client.daemon_stop()
            except Exception:
                pass
        else:
            return None
    last_error: Optional[str] = None
    _log("Ensuring the browser daemon is running...")
    for attempt in range(1, 4):
        if attempt > 1:
            _log(f"Retry {attempt}/3: cleaning up stale state...")
            try:
                browser_client.daemon_stop()
            except Exception:
                pass
        try:
            browser_client.daemon_start(profile_dir=profile)
            message = (
                "Browser daemon started"
                if attempt == 1
                else f"Browser daemon started on retry {attempt}"
            )
            _log(message)
            return None
        except RuntimeError as exc:
            last_error = str(exc)
            _log(f"Browser daemon startup failed (attempt {attempt}/3): {exc}")
    diagnostics = collect_daemon_diagnostics()
    parts = [f"Browser daemon failed to start after 3 attempts: {last_error}"]
    if diagnostics.get("stderr_tail"):
        parts.append(f"stderr tail: {diagnostics['stderr_tail'][-500:]}")
    if diagnostics.get("daemon_status"):
        parts.append(f"daemon status: {diagnostics['daemon_status']}")
    if diagnostics.get("daemon_health"):
        parts.append(f"daemon health: {diagnostics['daemon_health']}")
    return " | ".join(parts)


def collect_daemon_diagnostics() -> Dict[str, Any]:
    diagnostics: Dict[str, Any] = {}
    stderr_log = browser_client._browser_dir() / ".daemon-stderr.log"
    try:
        if stderr_log.exists():
            diagnostics["stderr_tail"] = "\n".join(
                stderr_log.read_text(encoding="utf-8").splitlines()[-40:]
            )
    except OSError:
        pass
    try:
        diagnostics["daemon_status"] = browser_client.daemon_status()
    except Exception:
        pass
    try:
        diagnostics["daemon_health"] = browser_client.daemon_health()
    except Exception:
        pass
    return diagnostics


__all__ = ["collect_daemon_diagnostics", "ensure_daemon_running"]
