"""Authenticated readiness checks for the product Browser QA daemon."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from yoke_harness.browser_client import DaemonState


def _client():
    # Resolve through the parent at call time so its public test seams remain
    # authoritative for state loading, process checks, and HTTP requests.
    from yoke_harness import browser_client

    return browser_client


def probe_daemon_health(
    state: "DaemonState",
    *,
    timeout: int = 10,
) -> Dict[str, Any]:
    client = _client()
    payload = client.daemon_request("/api/health", timeout=timeout, state=state)
    data = payload.get("data")
    if (
        payload.get("success") is not True
        or not isinstance(data, dict)
        or data.get("health") != "healthy"
    ):
        raise RuntimeError(
            "daemon health endpoint returned an unready response "
            f"(endpoint={state.endpoint}/api/health, pid={state.pid})"
        )
    return payload


def daemon_health(
    state: Optional["DaemonState"] = None,
    *,
    timeout: int = 10,
) -> Dict[str, Any]:
    client = _client()
    selected = state or client.DaemonState.load()
    if selected is None or not client.daemon_running(selected):
        raise RuntimeError("daemon not running")
    return probe_daemon_health(selected, timeout=timeout)


def daemon_status() -> Dict[str, Any]:
    client = _client()
    state = client.DaemonState.load()
    if state is None:
        return {"status": "not_running"}
    if client.daemon_running(state):
        try:
            client.daemon_health(state=state, timeout=1)
        except RuntimeError as exc:
            return {
                "status": "unready",
                "health": "unreachable",
                "endpoint": state.endpoint,
                "pid": state.pid,
                "error": str(exc),
            }
        return {
            "status": "running",
            "health": "healthy",
            "endpoint": state.endpoint,
            "pid": state.pid,
        }
    return {
        "status": "crashed",
        "health": "crashed",
        "endpoint": state.endpoint,
        "pid": state.pid,
    }


__all__ = ["daemon_health", "daemon_status", "probe_daemon_health"]
