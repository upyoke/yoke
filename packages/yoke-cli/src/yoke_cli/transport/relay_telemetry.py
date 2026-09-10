"""Machine-local spool for relay outcomes, flushed on the next call that lands.

A relay failure cannot be reported through the relay, so measuring how often
the relay fails needs somewhere to write that does not depend on it. Each
outcome is appended to one machine-local file, and the next call that
succeeds drains the file into ``events.emit``. Nothing polls, nothing runs in
the background, and a machine that never talks to the control plane again
just keeps a bounded file nobody reads.

A record leaves the spool only once it has actually landed — delivered, or
definitively refused. A spool that drops what it could not send has the
failure mode it exists to prevent, because delivery fails hardest exactly
when the outcomes are worth having. But "could not send" and "was refused"
are different failures: the relay being unreachable says nothing about
whether THIS record is valid, and a record the server has already evaluated
and permanently refused (bad authorization, a malformed payload) will read
exactly the same on every future attempt. Retrying that record forever turns
one refusal into a standing tax on every later successful call, so a
permanent refusal is quarantined — kept once as bounded local evidence,
never resent — while a transient failure (the relay itself did not answer)
stays in the spool for the next opportunity.

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

_OUTCOME_DELIVERED = "delivered"
_OUTCOME_TRANSIENT = "transient"
_OUTCOME_PERMANENT = "permanent"

# The dispatcher's own definitive refusals — the server evaluated this
# specific record and will refuse it identically on every future attempt.
# Anything else (transport failure, a permission check that could not reach
# its own DB, an error code this module has never seen) is treated as
# transient: the safe default keeps evidence rather than silently dropping a
# failure mode nobody has classified yet.
_PERMANENT_REFUSAL_CODES = frozenset(
    {
        "permission_denied",
        "payload_invalid",
        "retired_event_name",
        "ambiguous_project",
    }
)

_flushing = False


def spool_path() -> Path:
    """The machine-local spool file: records still waiting to be sent."""
    from yoke_cli.config.machine_config import yoke_home

    return yoke_home() / SPOOL_FILE_NAME


def quarantine_path() -> Path:
    """The machine-local file holding permanently refused outcomes.

    Kept separate from the retry spool: a record lands here once the server
    has definitively refused it (bad authorization, a malformed payload), so
    nothing here is ever retried — it is bounded diagnostic custody, not a
    queue.
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

    *project* names the universe the outcome was OBSERVED in — the caller's
    own request/session/connection authority at the moment of failure, not
    whatever universe the eventual flush happens to run under. Resolving it
    here, once per observed outcome, is what keeps a record's attribution
    stable: a flush that lands later, possibly against a different project
    entirely, must report the project the call actually belonged to rather
    than relabeling it into whichever project happens to call next. When the
    caller cannot name one, this falls back to the ambient checkout context
    of the process observing the failure — still the record's own moment,
    never the flush's.
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

    ``events.emit`` is project-scoped and the server refuses to guess one, so
    an envelope that cannot name its project is denied outright rather than
    silently defaulting. This never touches the DB — only the machine
    config's checkout->project map for the current process — because it
    stands in for request-level authority the caller did not supply, not a
    replacement for it.
    """
    try:
        from yoke_cli.commands._helpers import client_project_context

        return client_project_context() or ""
    except Exception:
        return ""


def _append(entries: List[Dict[str, Any]]) -> None:
    """Append spool entries up to the bounded cap. Never raises.

    The cap is what keeps a machine that never reconnects from growing the
    file forever, so it holds for records coming back from a failed flush
    exactly as it does for newly observed ones.
    """
    _append_bounded(spool_path, entries, SPOOL_MAX_RECORDS)


def _quarantine(entry: Dict[str, Any]) -> None:
    """Retain one permanently refused record as bounded local evidence."""
    _append_bounded(quarantine_path, [entry], QUARANTINE_MAX_RECORDS)


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

    A transient failure — the relay itself did not answer this particular
    emit — ends the pass rather than working through the rest: this runs
    inline on a real caller's call, and a relay that just refused is not
    worth the wait a whole queue would cost them, so the failing record and
    everything behind it goes back on the spool for the next opportunity. A
    permanent failure is different: the relay is healthy and has already
    evaluated this specific record and refused it for good (authorization,
    payload shape), so retrying it would only repeat the same refusal on
    every future call. That record is quarantined instead of requeued, and
    the pass continues — one bad record says nothing about the next one.
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
            outcome = _emit(entry)
            if outcome == _OUTCOME_DELIVERED:
                sent += 1
                continue
            if outcome == _OUTCOME_PERMANENT:
                _quarantine(entry)
                continue
            _append(records[index:])
            break
        return sent
    except Exception:
        return 0
    finally:
        _flushing = False


def _emit(entry: Dict[str, Any]) -> str:
    """Send one record as an event. Returns delivered/transient/permanent."""
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
    from yoke_contracts.api.function_call import TargetRef

    transport_delivered = entry.get("transport_delivered") is True
    application_succeeded = entry.get("application_succeeded")
    name = EVENT_RETRIED if transport_delivered else EVENT_EXHAUSTED
    session_id = str(entry.get("session_id") or "")
    project = str(entry.get("project") or "")
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
        )
    except Exception:
        # The transport itself could not be reached — indistinguishable from
        # any other transient delivery failure, so keep the record.
        return _OUTCOME_TRANSIENT
    if response.success:
        return _OUTCOME_DELIVERED
    code = response.error.code if response.error else ""
    if code in _PERMANENT_REFUSAL_CODES:
        return _OUTCOME_PERMANENT
    return _OUTCOME_TRANSIENT


__all__ = [
    "EVENT_EXHAUSTED",
    "EVENT_RETRIED",
    "QUARANTINE_FILE_NAME",
    "QUARANTINE_MAX_RECORDS",
    "SPOOL_FILE_NAME",
    "SPOOL_MAX_RECORDS",
    "TRANSPORT_FAILED_CODE",
    "drain",
    "flush",
    "quarantine_path",
    "record",
    "spool_path",
]
