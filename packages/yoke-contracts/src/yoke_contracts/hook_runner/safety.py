"""Lifecycle failure replies and the machine-local Stop circuit breaker.

This state is required safety bookkeeping, independent of config, the
resident, the control plane and telemetry. Only hashes and counters persist.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

from yoke_contracts import platform_file_lock
from yoke_contracts.hook_diagnostics import format_hook_diagnostic
from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.machine_config.paths import yoke_home


LIFECYCLE_EVENTS = frozenset({"Stop", "SessionStart", "SessionEnd"})
BLOCK_LIMIT = 3
WINDOW_SECONDS = 300
MAX_SESSIONS = 256


def parse_payload(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _state_path() -> Path:
    # cache_dir() reads the config that may be broken. This fixed safety
    # owner must remain available even when its configured cache is not.
    return yoke_home() / "hook-safety" / "counters.json"


def _update(payload: dict, event: str, update: Callable[[dict, float], bool]) -> bool:
    session = payload.get("session_id") or payload.get("conversation_id")
    session = session or os.environ.get("YOKE_SESSION_ID")
    if not session:
        raise OSError("hook safety session identity unavailable")
    key = _digest(f"{session}:{event}")
    target = _state_path()
    create_private_directory(target.parent)
    descriptor = os.open(target, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
        platform_file_lock.acquire_exclusive_nonblocking(handle.fileno())
        try:
            raw = handle.read(131072)
            state = json.loads(raw) if raw else {}
            if not isinstance(state, dict):
                raise ValueError("hook safety counters are not an object")
            now = time.time()
            state = {
                k: v
                for k, v in state.items()
                if isinstance(v, dict) and 0 <= now - v.get("at", 0) < WINDOW_SECONDS
            }
            entry = state.setdefault(key, {})
            result = update(entry, now)
            entry["at"] = now
            if len(state) > MAX_SESSIONS:
                state = dict(
                    sorted(state.items(), key=lambda pair: pair[1]["at"])[
                        -MAX_SESSIONS:
                    ]
                )
            handle.seek(0)
            json.dump(state, handle)
            handle.truncate()
            return result
        finally:
            platform_file_lock.release_exclusive(handle.fileno())


def failure_message(event: str, payload: dict, reason: str) -> str:
    """One full diagnosis per identical failure window, then a short reference."""
    fingerprint = _digest(reason)

    def update(entry: dict, now: float) -> bool:
        first = (
            entry.get("warning") != fingerprint
            or now - entry.get("warned_at", 0) >= WINDOW_SECONDS
        )
        if first:
            entry.update(warning=fingerprint, warned_at=now)
        return first

    try:
        first = _update(payload, event, update)
    except (OSError, ValueError, TypeError):
        first = True
    if first:
        return f"{reason}; repair Yoke configuration or connectivity, then retry."
    return f"hook_infrastructure_unavailable: repeated failure {fingerprint[:12]}; follow the earlier recovery."


def allow_stdout(executor: str) -> str:
    return "{}" if executor.startswith(("codex", "cursor")) else ""


def infrastructure_reply(
    event: str, payload: dict, executor: str, reason: str
) -> tuple[str, int, bool]:
    message = failure_message(event, payload, reason)
    if event in LIFECYCLE_EVENTS:
        sys.stderr.write(
            format_hook_diagnostic(
                event, f"WARNING: {message} degraded to no-op allow.\n"
            )
        )
        return (allow_stdout(executor) if event != "SessionStart" else ""), 0, False
    if executor.startswith("cursor"):
        return (
            json.dumps(
                {
                    "permission": "deny",
                    "user_message": message,
                    "agent_message": message,
                }
            ),
            0,
            True,
        )
    if executor.startswith("codex"):
        return (
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": event,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": message,
                    }
                }
            ),
            0,
            True,
        )
    return message, 2, True


def stop_reentry(payload: dict) -> bool:
    """Claude/Codex report stop_hook_active; Cursor reports loop_count."""
    active = payload.get("stop_hook_active")
    if active is True or str(active).lower() in {"true", "1"}:
        return True
    loops = payload.get("loop_count")
    return isinstance(loops, (int, float)) and not isinstance(loops, bool) and loops > 0


def protect_stop(
    event: str, payload: dict, stdout: str, code: int, executor: str
) -> tuple[str, int]:
    """Bound every adapter's final continuation response, once on the client."""
    if event != "Stop":
        return stdout, code
    body = parse_payload(stdout)
    inner = body.get("hookSpecificOutput") or {}
    blocked = (
        code == 2
        or body.get("decision") == "block"
        or body.get("permission") == "deny"
        or bool(body.get("followup_message"))
        or (isinstance(inner, dict) and inner.get("permissionDecision") == "deny")
    )
    if not blocked:
        try:
            _update(
                payload, event, lambda entry, _now: entry.pop("hold", None) is not None
            )
        except (OSError, ValueError, TypeError):
            pass
        return stdout, code
    reason = (
        body.get("reason")
        or body.get("followup_message")
        or (inner.get("permissionDecisionReason") if isinstance(inner, dict) else None)
        or stdout
    )
    fingerprint = _digest(str(reason))

    def update(entry: dict, now: float) -> bool:
        hold = entry.get("hold") or {}
        if (
            hold.get("reason") != fingerprint
            or now - hold.get("since", 0) >= WINDOW_SECONDS
        ):
            hold = {"reason": fingerprint, "since": now, "count": 0}
        hold["count"] += 1
        entry["hold"] = hold
        return hold["count"] > BLOCK_LIMIT

    recovery = "hook_stop_reentry"
    if not stop_reentry(payload):
        try:
            if not _update(payload, event, update):
                return stdout, code
            recovery = "hook_stop_block_limit"
        except (OSError, ValueError, TypeError):
            recovery = "hook_stop_safety_unavailable"
    sys.stderr.write(
        format_hook_diagnostic(
            event,
            f"WARNING: {recovery}: allowing Stop; repair Yoke before resuming work.\n",
        )
    )
    return allow_stdout(executor), 0
