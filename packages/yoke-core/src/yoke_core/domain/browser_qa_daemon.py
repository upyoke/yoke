"""Browser daemon lifecycle helpers for the Browser QA orchestrator.

Owns daemon-startup auto-recovery, diagnostics collection on failure, and the
``BrowserDaemonStartupFailed`` event emission. Sibling modules call these via
the parent ``browser_qa`` module so test patches such as
``mock.patch.object(browser_qa, "_collect_daemon_diagnostics", ...)`` apply
without rebinding sibling-local names.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from yoke_contracts.browser_identity import DEFAULT_IDENTITY
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_harness.browser_client_readiness import DAEMON_LOG_NAME
from yoke_harness.browser_daemon_profile import recover_unhealthy_daemon


_DAEMON_MAX_RETRIES = 2  # additional attempts after the first failure


def _collect_daemon_diagnostics(*, profile_dir: str | None = None) -> Dict[str, Any]:
    """Collect diagnostics from the browser daemon for failure reporting.

    Gathers the daemon log tail, daemon state, and health check results when
    available.  Never raises — returns whatever diagnostics it can collect.
    """
    from yoke_core.domain.browser_client import (
        daemon_status as _daemon_status,
        daemon_health as _daemon_health,
        _state_file_path,
        DaemonState,
    )

    diag: Dict[str, Any] = {}

    # Daemon log tail
    daemon_log = _state_file_path(profile_dir).parent / DAEMON_LOG_NAME
    try:
        if daemon_log.exists():
            text = daemon_log.read_text()
            # Last 40 lines
            lines = text.splitlines()[-40:]
            diag["log_tail"] = "\n".join(lines)
    except OSError:
        pass

    # Daemon status (always safe to call)
    try:
        diag["daemon_status"] = _daemon_status(profile_dir=profile_dir)
    except Exception:
        pass

    # Health (only if daemon process might be alive)
    try:
        diag["daemon_health"] = _daemon_health(
            state=DaemonState.load(_state_file_path(profile_dir))
        )
    except Exception:
        pass

    return diag


def _ensure_daemon_running(
    *,
    subject: int | str | None = None,
    project: str = "",
    identity: str = DEFAULT_IDENTITY,
) -> Optional[str]:
    """Ensure browser daemon is running. Returns error message or None.

    Each profile owns a separate daemon, state file, log and endpoint. A retry
    stops only this profile's verifiably unhealthy process; a healthy process
    and every other profile's captures survive startup failures.
    """
    # Import lazily so tests patching browser_qa._log /
    # browser_qa._collect_daemon_diagnostics / browser_qa._emit_daemon_startup_failed_event
    # via mock.patch.object(browser_qa, ...) take effect on this caller.
    from yoke_core.domain import browser_qa as _bqa
    from yoke_core.domain import browser_client
    from yoke_core.domain.browser_client import daemon_start

    from yoke_contracts.browser_identity import BrowserIdentityError
    from yoke_cli.config.browser_identities import resolve_identity
    from yoke_cli.config.browser_profile import (
        profile_project_key,
        resolve_authorized_profile,
    )
    from yoke_cli.config.project_slug_lookup import ProjectSlugLookupError

    try:
        if identity != DEFAULT_IDENTITY:
            resolve_identity(profile_project_key(project), identity)
        profile_path, profile_note = resolve_authorized_profile(
            project, identity=identity
        )
    except (ProjectSlugLookupError, BrowserIdentityError) as exc:
        _bqa._log(str(exc))
        return str(exc)
    _bqa._log(profile_note)
    profile = str(profile_path) if profile_path else None

    # First attempt
    last_err: Optional[str] = None
    _bqa._log("Ensuring the browser daemon is running...")
    try:
        daemon_start(profile_dir=profile)
        _bqa._log("Browser daemon ready")
        return None
    except RuntimeError as first_err:
        last_err = str(first_err)
        _bqa._log(
            f"Browser daemon startup failed (attempt 1/{_DAEMON_MAX_RETRIES + 1}): {first_err}"
        )

    # Retry loop with cleanup
    for attempt in range(2, _DAEMON_MAX_RETRIES + 2):
        _bqa._log(
            f"Retry {attempt}/{_DAEMON_MAX_RETRIES + 1}: cleaning up stale state..."
        )
        try:
            recover_unhealthy_daemon(browser_client, profile)
        except RuntimeError as cleanup_error:
            last_err = str(cleanup_error)
            _bqa._log(last_err)
            continue

        time.sleep(1)

        _bqa._log(
            f"Retry {attempt}/{_DAEMON_MAX_RETRIES + 1}: attempting daemon start..."
        )
        try:
            daemon_start(profile_dir=profile)
            _bqa._log(f"Browser daemon started on retry {attempt}")
            return None
        except RuntimeError as retry_err:
            last_err = str(retry_err)
            _bqa._log(f"Retry {attempt}/{_DAEMON_MAX_RETRIES + 1} failed: {retry_err}")

    # All retries exhausted — collect diagnostics and emit event.
    diagnostics = _bqa._collect_daemon_diagnostics(profile_dir=profile or "")
    _bqa._log(f"Browser daemon failed after {_DAEMON_MAX_RETRIES + 1} attempts")
    if diagnostics.get("log_tail"):
        _bqa._log(f"Daemon log tail:\n{diagnostics['log_tail']}")
    if diagnostics.get("daemon_status"):
        _bqa._log(f"Daemon status: {diagnostics['daemon_status']}")
    if diagnostics.get("daemon_health"):
        _bqa._log(f"Daemon health: {diagnostics['daemon_health']}")

    try:
        _bqa._emit_daemon_startup_failed_event(
            attempt_count=_DAEMON_MAX_RETRIES + 1,
            last_error=last_err or "unknown",
            diagnostics=diagnostics,
            subject=subject,
            project=project,
        )
    except Exception as emit_exc:
        _bqa._log(f"Warning: event emission failed: {emit_exc}")

    # Build a rich error message
    parts = [
        f"Browser daemon failed to start after {_DAEMON_MAX_RETRIES + 1} attempts: {last_err}"
    ]
    if diagnostics.get("log_tail"):
        parts.append(f"daemon log tail: {diagnostics['log_tail'][-500:]}")
    if diagnostics.get("daemon_status"):
        parts.append(f"daemon status: {diagnostics['daemon_status']}")
    if diagnostics.get("daemon_health"):
        parts.append(f"daemon health: {diagnostics['daemon_health']}")

    return " | ".join(parts)


def _emit_daemon_startup_failed_event(
    attempt_count: int,
    last_error: str,
    diagnostics: Dict[str, Any],
    *,
    subject: int | str | None = None,
    project: str = "",
) -> None:
    """Emit a BrowserDaemonStartupFailed event via the runtime event platform."""
    from yoke_core.domain.events import emit_event as _native_emit

    session_id = resolve_ambient_session_id() or ""
    kwargs: Dict[str, Any] = {
        "event_kind": "system",
        "event_type": "browser_daemon",
        "source_type": "backend",
        "session_id": session_id,
        "severity": "ERROR",
        "outcome": "failed",
        "project": project,
        "context": {
            "attempt_count": attempt_count,
            "last_error": last_error,
            "diagnostics": diagnostics,
            "subject": subject,
        },
    }
    if isinstance(subject, int):
        kwargs["item_id"] = subject
    _native_emit("BrowserDaemonStartupFailed", **kwargs)
