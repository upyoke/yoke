"""Browser daemon startup and diagnostics for product browser QA."""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_harness import browser_client
from yoke_harness.browser_qa_results import log


def ensure_daemon_running() -> Optional[str]:
    if browser_client.daemon_running():
        return None
    last_error: Optional[str] = None
    log("Browser daemon not running, starting...")
    for attempt in range(1, 4):
        if attempt > 1:
            log(f"Retry {attempt}/3: cleaning up stale state...")
            try:
                browser_client.daemon_stop()
            except Exception:
                pass
        try:
            browser_client.daemon_start()
            message = (
                "Browser daemon started"
                if attempt == 1
                else f"Browser daemon started on retry {attempt}"
            )
            log(message)
            return None
        except RuntimeError as exc:
            last_error = str(exc)
            log(f"Browser daemon startup failed (attempt {attempt}/3): {exc}")
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
