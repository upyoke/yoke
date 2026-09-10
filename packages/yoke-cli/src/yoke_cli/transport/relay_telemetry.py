"""Machine-local spool for relay outcomes, flushed on the next call that lands.

A relay failure cannot be reported through the relay, so measuring how often
the relay fails needs somewhere to write that does not depend on it. Each
outcome is appended to one machine-local file, and the next call that
succeeds drains the file into ``events.emit``. Nothing polls, nothing runs in
the background, and a machine that never talks to the control plane again
just keeps a bounded file nobody reads.

A record leaves the spool only once it has actually landed — delivered, or
definitively refused. A spool that drops what it could not send has the
failure mode it exists to prevent. But "could not send" and "was refused"
differ: the relay being unreachable says nothing about whether THIS record
is valid, and a record the server has already evaluated and permanently
refused (bad authorization, a malformed payload) reads the same on every
future attempt. Retrying it forever turns one refusal into a standing tax
on every later successful call, so a permanent refusal is quarantined —
kept once as bounded local evidence, with the code that explains it, never
resent — while a transient failure (the relay itself did not answer) stays
in the spool.

Two identities travel with every record and are not the same thing. ``env``
is the CONNECTION observed (which universe); ``project`` is the project
WITHIN that universe — meaningful only paired with its own env, since two
universes can both have a project "1" meaning two unrelated projects. Every
emit is therefore pinned back to its own record's env, never whatever
connection is active when the flush runs. A record with no project at all
is never dispatched: the dispatcher refuses an unnamed project outright, so
sending it would only spend a call on an answer already known.

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
from typing import Any, Callable, Dict, List

SPOOL_FILE_NAME = "relay-telemetry.jsonl"
SPOOL_MAX_RECORDS = 500
QUARANTINE_FILE_NAME = "relay-telemetry-quarantine.jsonl"
QUARANTINE_MAX_RECORDS = 100
EVENT_RETRIED = "RelayTransportRetrySucceeded"
EVENT_EXHAUSTED = "RelayTransportAttemptsExhausted"
TRANSPORT_FAILED_CODE = "https_transport_failed"

# A client-local classification: no server was ever asked, because no
# project was ever established to ask it about.
UNRESOLVED_PROJECT_REASON = "unresolved_project"

_OUTCOME_DELIVERED = "delivered"
_OUTCOME_TRANSIENT = "transient"
_OUTCOME_PERMANENT = "permanent"

# The dispatcher's own definitive refusals, repeated identically on every
# future attempt. Anything else (transport failure, an unclassified code)
# is transient by default: keep evidence rather than silently drop it.
_PERMANENT_REFUSAL_CODES = frozenset(
    {"permission_denied", "payload_invalid", "retired_event_name", "ambiguous_project"}
)

_flushing = False


def spool_path() -> Path:
    """The machine-local spool file: records still waiting to be sent."""
    from yoke_cli.config.machine_config import yoke_home

    return yoke_home() / SPOOL_FILE_NAME


def quarantine_path() -> Path:
    """The machine-local file holding permanently refused outcomes.

    Separate from the retry spool: a record lands here once definitively
    refused, so nothing here is ever retried — bounded diagnostic custody,
    not a queue.
    """
    from yoke_cli.config.machine_config import yoke_home

    return yoke_home() / QUARANTINE_FILE_NAME


def record(
    *,
    function_id: str,
    session_id: str,
    env: str,
    attempts: int,
    transport_delivered: bool,
    application_succeeded: bool | None,
    failure_class: str,
    project: str = "",
) -> None:
    """Append one relay outcome. Never raises — telemetry is not the work.

    *env* and *project* are both resolved at the caller's own moment of
    failure — the connection and, within it, the project the observed call
    belonged to — not whatever the eventual flush happens to run under.
    Stamping both here, once per observed outcome, is what keeps a record's
    attribution stable rather than relabeled into whichever authority a
    later call happens to use. When the caller names no project, this falls
    back to the ambient checkout context of the observing process.
    """
    _append(
        [
            {
                "function": function_id,
                "session_id": session_id,
                "env": env,
                "attempts": attempts,
                "transport_delivered": transport_delivered,
                "application_succeeded": application_succeeded,
                "failure_class": failure_class,
                "project": project or _project_context(),
            }
        ]
    )


def _project_context() -> str:
    """Best-effort ambient project for a caller that named none explicitly.

    ``events.emit`` refuses to guess a project itself, so this stands in
    for request-level authority the caller did not supply. Never touches
    the DB — only the machine config's checkout->project map.
    """
    try:
        from yoke_cli.commands._helpers import client_project_context

        return client_project_context() or ""
    except Exception:
        return ""


def _append(entries: List[Dict[str, Any]]) -> None:
    """Append spool entries up to the bounded cap. Never raises.

    The cap keeps a machine that never reconnects from growing the file
    forever, for records returning from a failed flush same as new ones.
    """
    _append_bounded(spool_path, entries, SPOOL_MAX_RECORDS)


def _quarantine(entry: Dict[str, Any], *, reason: str) -> None:
    """Retain one permanently refused record as bounded local evidence.

    *reason* names why THIS record is quarantined — the dispatcher's own
    refusal code, or :data:`UNRESOLVED_PROJECT_REASON` when no call was
    ever made — distinct from ``failure_class``, which still names what
    went wrong with the originally OBSERVED call.
    """
    quarantined = dict(entry)
    quarantined["quarantine_reason"] = reason
    _append_bounded(quarantine_path, [quarantined], QUARANTINE_MAX_RECORDS)


def _append_bounded(
    resolve_path: Callable[[], Path], entries: List[Dict[str, Any]], cap: int
) -> None:
    try:
        path = resolve_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        room = cap - _record_count(path, cap)
        if room <= 0:
            return
        with path.open("a", encoding="utf-8") as handle:
            for entry in entries[:room]:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except Exception:
        return


def _record_count(path: Path, cap: int) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except FileNotFoundError:
        return 0
    except Exception:
        return cap


def drain() -> List[Dict[str, Any]]:
    """Read every spooled record and remove the file. Never raises.

    Path resolution is inside the guard too — telemetry is never the
    reason a call fails.
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
    known good. The reentrancy guard matters: emitting goes back through
    the same relay, so without it the first flush would recurse.

    A transient failure — the relay itself did not answer — ends the pass:
    this runs inline on a real caller's call, so the failing record and
    everything behind it goes back on the spool rather than hammering a
    relay that just refused. A permanent failure means the relay is
    healthy and has already evaluated this record for good (authorization,
    payload shape, no project at all), so it is quarantined instead of
    requeued and the pass continues — one bad record says nothing about
    the next one.
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
        for index, entry in enumerate(records):
            if not entry.get("project"):
                _quarantine(entry, reason=UNRESOLVED_PROJECT_REASON)
                continue
            outcome, reason = _emit(entry)
            if outcome == _OUTCOME_DELIVERED:
                sent += 1
                continue
            if outcome == _OUTCOME_PERMANENT:
                _quarantine(entry, reason=reason)
                continue
            _append(records[index:])
            break
        return sent
    except Exception:
        return 0
    finally:
        _flushing = False


def _emit(entry: Dict[str, Any]) -> tuple[str, str]:
    """Send one record. Returns (outcome, reason); reason is the refusal
    code, empty unless outcome is permanent. Dispatch is pinned to this
    record's own ``env`` (``relay_env=``), never the connection active at
    flush time; an unreachable named env answers ``relay_env_unavailable``,
    not in the permanent set, so the record stays queued.
    """
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
    from yoke_contracts.api.function_call import TargetRef

    transport_delivered = entry.get("transport_delivered") is True
    application_succeeded = entry.get("application_succeeded")
    name = EVENT_RETRIED if transport_delivered else EVENT_EXHAUSTED
    session_id = str(entry.get("session_id") or "")
    project = str(entry.get("project") or "")
    env = str(entry.get("env") or "")
    payload: Dict[str, Any] = {
        "name": name,
        "kind": "system",
        "type": "relay_transport",
        # "cli" is not a member of the event platform's closed source-type
        # vocabulary. The "cli" carried beside these two events in the
        # curated registry is their owner_service, which is a different
        # field; every cli-service event is a system event, and so is this.
        "source_type": "system",
        "severity": "INFO" if transport_delivered else "WARN",
        "outcome": "completed" if transport_delivered else "failed",
        "context": {
            "function": str(entry.get("function") or ""),
            "env": str(entry.get("env") or ""),
            "attempts": entry.get("attempts"),
            "transport_outcome": ("delivered" if transport_delivered else "exhausted"),
            "application_outcome": (
                "succeeded"
                if application_succeeded is True
                else "failed"
                if application_succeeded is False
                else "not_reached"
            ),
            "failure_class": str(entry.get("failure_class") or ""),
        },
    }
    if project:
        payload["project"] = project
    try:
        response = call_dispatcher(
            function_id="events.emit",
            target=TargetRef(kind="global"),
            actor=build_actor(session_id=session_id) if session_id else None,
            payload=payload,
            relay_env=env or None,
        )
    except Exception:
        # The transport itself could not be reached — indistinguishable from
        # any other transient delivery failure, so keep the record.
        return _OUTCOME_TRANSIENT, ""
    if response.success:
        return _OUTCOME_DELIVERED, ""
    code = response.error.code if response.error else ""
    if code in _PERMANENT_REFUSAL_CODES:
        return _OUTCOME_PERMANENT, code
    return _OUTCOME_TRANSIENT, ""


__all__ = [
    "EVENT_EXHAUSTED",
    "EVENT_RETRIED",
    "QUARANTINE_FILE_NAME",
    "QUARANTINE_MAX_RECORDS",
    "SPOOL_FILE_NAME",
    "SPOOL_MAX_RECORDS",
    "TRANSPORT_FAILED_CODE",
    "UNRESOLVED_PROJECT_REASON",
    "drain",
    "flush",
    "quarantine_path",
    "record",
    "spool_path",
]
