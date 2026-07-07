"""Browser daemon lifecycle helpers for the Browser QA orchestrator.

Owns daemon-startup auto-recovery, diagnostics collection on failure, and the
``BrowserDaemonStartupFailed`` event emission. Sibling modules call these via
the parent ``browser_qa`` module so test patches such as
``mock.patch.object(browser_qa, "_collect_daemon_diagnostics", ...)`` apply
without rebinding sibling-local names.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional


_DAEMON_MAX_RETRIES = 2  # additional attempts after the first failure


def _collect_daemon_diagnostics() -> Dict[str, Any]:
    """Collect diagnostics from the browser daemon for failure reporting.

    Gathers stderr log tail, daemon state, and health check results when
    available.  Never raises — returns whatever diagnostics it can collect.
    """
    from yoke_core.domain.browser_client import (
        daemon_status as _daemon_status,
        daemon_health as _daemon_health,
        _browser_dir,
    )

    diag: Dict[str, Any] = {}

    # Stderr log tail
    stderr_log = _browser_dir() / ".daemon-stderr.log"
    try:
        if stderr_log.exists():
            text = stderr_log.read_text()
            # Last 40 lines
            lines = text.splitlines()[-40:]
            diag["stderr_tail"] = "\n".join(lines)
    except OSError:
        pass

    # Daemon status (always safe to call)
    try:
        diag["daemon_status"] = _daemon_status()
    except Exception:
        pass

    # Health (only if daemon process might be alive)
    try:
        diag["daemon_health"] = _daemon_health()
    except Exception:
        pass

    return diag


def _ensure_daemon_running(
    *,
    item_id: Optional[int] = None,
    project: str = "yoke",
) -> Optional[str]:
    """Ensure browser daemon is running. Returns error message or None.

    Performs bounded auto-recovery — on startup failure, stops stale
    state, waits briefly, and retries up to ``_DAEMON_MAX_RETRIES`` additional
    times before giving up.
    """
    # Import lazily so tests patching browser_qa._log /
    # browser_qa._collect_daemon_diagnostics / browser_qa._emit_daemon_startup_failed_event
    # via mock.patch.object(browser_qa, ...) take effect on this caller.
    from yoke_core.domain import browser_qa as _bqa
    from yoke_core.domain.browser_client import (
        daemon_running,
        daemon_start,
        daemon_stop,
    )

    # Check if already running
    if daemon_running():
        return None

    # First attempt
    last_err: Optional[str] = None
    _bqa._log("Browser daemon not running, starting...")
    try:
        daemon_start()
        _bqa._log("Browser daemon started")
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
            daemon_stop()
        except Exception:
            pass  # stop may fail if daemon is already dead — that's fine

        time.sleep(1)

        _bqa._log(
            f"Retry {attempt}/{_DAEMON_MAX_RETRIES + 1}: attempting daemon start..."
        )
        try:
            daemon_start()
            _bqa._log(f"Browser daemon started on retry {attempt}")
            return None
        except RuntimeError as retry_err:
            last_err = str(retry_err)
            _bqa._log(
                f"Retry {attempt}/{_DAEMON_MAX_RETRIES + 1} failed: {retry_err}"
            )

    # All retries exhausted — collect diagnostics and emit event.
    diagnostics = _bqa._collect_daemon_diagnostics()
    _bqa._log(f"Browser daemon failed after {_DAEMON_MAX_RETRIES + 1} attempts")
    if diagnostics.get("stderr_tail"):
        _bqa._log(f"Daemon stderr tail:\n{diagnostics['stderr_tail']}")
    if diagnostics.get("daemon_status"):
        _bqa._log(f"Daemon status: {diagnostics['daemon_status']}")
    if diagnostics.get("daemon_health"):
        _bqa._log(f"Daemon health: {diagnostics['daemon_health']}")

    try:
        _bqa._emit_daemon_startup_failed_event(
            attempt_count=_DAEMON_MAX_RETRIES + 1,
            last_error=last_err or "unknown",
            diagnostics=diagnostics,
            item_id=item_id,
            project=project,
        )
    except Exception as emit_exc:
        _bqa._log(f"Warning: event emission failed: {emit_exc}")

    # Build a rich error message
    parts = [
        f"Browser daemon failed to start after {_DAEMON_MAX_RETRIES + 1} attempts: {last_err}"
    ]
    if diagnostics.get("stderr_tail"):
        parts.append(f"stderr tail: {diagnostics['stderr_tail'][-500:]}")
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
    item_id: Optional[int] = None,
    project: str = "yoke",
) -> None:
    """Emit a BrowserDaemonStartupFailed event via the runtime event platform."""
    from yoke_core.domain.events import emit_event as _native_emit

    session_id = (
        os.environ.get("YOKE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CODEX_THREAD_ID")
        or ""
    )
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
        },
    }
    if item_id is not None:
        kwargs["item_id"] = f"YOK-{item_id}"
    _native_emit("BrowserDaemonStartupFailed", **kwargs)
