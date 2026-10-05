"""Browser daemon startup and diagnostics for product browser QA."""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from yoke_harness import browser_client
from yoke_harness.browser_client_readiness import DAEMON_LOG_NAME
from yoke_harness.browser_daemon_profile import recover_unhealthy_daemon


def _log(message: str) -> None:
    """Write one browser-runtime diagnostic without runner-layer coupling."""
    print(f"[browser-runtime] {message}", file=sys.stderr)


def ensure_daemon_running(project: Optional[str] = None) -> Optional[str]:
    """Ensure the daemon runs on ``project``'s persistent browser profile.

    An authorized profile makes every context the daemon hands out signed into
    whatever the operator signed into; a project with no profile keeps the
    clean-context behavior. Every profile owns an independent daemon;
    another project's live capture is never stopped or reused.
    """
    from yoke_cli.config.browser_profile import resolve_authorized_profile
    from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError

    try:
        profile_path, profile_note = resolve_authorized_profile(project)
    except ProjectSlugLookupError as exc:
        return str(exc)
    _log(profile_note)
    profile = str(profile_path) if profile_path else None

    last_error: Optional[str] = None
    _log("Ensuring the browser daemon is running...")
    for attempt in range(1, 4):
        try:
            recover_unhealthy_daemon(browser_client, profile)
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
    diagnostics = collect_daemon_diagnostics(profile_dir=profile or "")
    parts = [f"Browser daemon failed to start after 3 attempts: {last_error}"]
    if diagnostics.get("log_tail"):
        parts.append(f"daemon log tail: {diagnostics['log_tail'][-500:]}")
    if diagnostics.get("daemon_status"):
        parts.append(f"daemon status: {diagnostics['daemon_status']}")
    if diagnostics.get("daemon_health"):
        parts.append(f"daemon health: {diagnostics['daemon_health']}")
    return " | ".join(parts)


def collect_daemon_diagnostics(*, profile_dir: str | None = None) -> Dict[str, Any]:
    diagnostics: Dict[str, Any] = {}
    daemon_log = browser_client._state_file_path(profile_dir).parent / DAEMON_LOG_NAME
    try:
        if daemon_log.exists():
            diagnostics["log_tail"] = "\n".join(
                daemon_log.read_text(encoding="utf-8").splitlines()[-40:]
            )
    except OSError:
        pass
    try:
        diagnostics["daemon_status"] = browser_client.daemon_status(
            profile_dir=profile_dir
        )
    except Exception:
        pass
    try:
        diagnostics["daemon_health"] = browser_client.daemon_health(
            state=browser_client.DaemonState.load(
                browser_client._state_file_path(profile_dir)
            )
        )
    except Exception:
        pass
    return diagnostics


__all__ = ["collect_daemon_diagnostics", "ensure_daemon_running"]
