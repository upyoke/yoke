"""Machine-local spool for relay outcomes, flushed on the next call that lands.

A relay failure cannot be reported through the relay, so measuring how often
the relay fails needs somewhere to write that does not depend on it. Each
outcome is appended to one machine-local file, and the next call that
succeeds drains the file into ``events.emit``. Nothing polls, nothing runs in
the background, and a machine that never talks to the control plane again
just keeps a bounded file nobody reads.

Only the two outcomes worth counting are recorded: a call that needed more
than one attempt and got there, and a call that ran out of attempts. The
ordinary first-try success is the overwhelming majority and recording it
would make the spool a write amplifier for no signal.

Per-harness rates come out of the join, not out of this file: each record
carries the ``session_id`` the call was made under, and the executor lives on
that session's row. Nothing here needs to know which harness it is running
in, which is what keeps the rate honest when a harness is added.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

SPOOL_FILE_NAME = "relay-telemetry.jsonl"
SPOOL_MAX_RECORDS = 500
EVENT_RETRIED = "RelayTransportRetrySucceeded"
EVENT_EXHAUSTED = "RelayTransportAttemptsExhausted"

_flushing = False


def spool_path() -> Path:
    """The machine-local spool file."""
    from yoke_cli.config.machine_config import yoke_home

    return yoke_home() / SPOOL_FILE_NAME


def record(
    *,
    function_id: str,
    session_id: str,
    env: str,
    attempts: int,
    succeeded: bool,
    failure_class: str,
) -> None:
    """Append one relay outcome. Never raises — telemetry is not the work."""
    entry = {
        "function": function_id,
        "session_id": session_id,
        "env": env,
        "attempts": attempts,
        "succeeded": succeeded,
        "failure_class": failure_class,
    }
    try:
        path = spool_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if _record_count(path) >= SPOOL_MAX_RECORDS:
            return
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except Exception:
        return


def _record_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except FileNotFoundError:
        return 0
    except Exception:
        return SPOOL_MAX_RECORDS


def drain() -> List[Dict[str, Any]]:
    """Read every spooled record and remove the file. Never raises.

    Resolving the path is inside the guard because it reads machine config,
    which is one more thing that can fail on a machine already having a bad
    day. Telemetry is never the reason a call fails.
    """
    try:
        path = spool_path()
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    records: List[Dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    try:
        os.unlink(path)
    except OSError:
        return records
    return records


def flush() -> int:
    """Emit every spooled record as an event. Returns how many were sent.

    Called only after a relay call has just landed, so the transport is
    known good. The reentrancy guard matters because emitting goes back
    through the same relay: without it the first flush would recurse
    through its own success path.
    """
    global _flushing
    if _flushing:
        return 0
    _flushing = True
    try:
        records = drain()
        if not records:
            return 0
        sent = 0
        for entry in records:
            if _emit(entry):
                sent += 1
        return sent
    except Exception:
        return 0
    finally:
        _flushing = False


def _emit(entry: Dict[str, Any]) -> bool:
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
    from yoke_contracts.api.function_call import TargetRef

    succeeded = bool(entry.get("succeeded"))
    name = EVENT_RETRIED if succeeded else EVENT_EXHAUSTED
    session_id = str(entry.get("session_id") or "")
    try:
        response = call_dispatcher(
            function_id="events.emit",
            target=TargetRef(kind="global"),
            actor=build_actor(session_id=session_id) if session_id else None,
            payload={
                "name": name,
                "kind": "system",
                "type": "relay_transport",
                "source_type": "cli",
                "severity": "INFO" if succeeded else "WARN",
                "outcome": "completed" if succeeded else "failed",
                "context": {
                    "function": str(entry.get("function") or ""),
                    "env": str(entry.get("env") or ""),
                    "attempts": entry.get("attempts"),
                    "failure_class": str(entry.get("failure_class") or ""),
                },
            },
        )
    except Exception:
        return False
    return bool(response.success)


__all__ = [
    "EVENT_EXHAUSTED",
    "EVENT_RETRIED",
    "SPOOL_FILE_NAME",
    "SPOOL_MAX_RECORDS",
    "drain",
    "flush",
    "record",
    "spool_path",
]
