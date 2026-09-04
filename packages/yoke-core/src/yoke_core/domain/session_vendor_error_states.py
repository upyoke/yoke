"""Which live sessions the model provider stopped, and what each is owed.

A turn that dies on the provider's side has nothing wrong with it. The
worker's work is intact, its lane is intact, its claim is intact; the
model refused to answer once. On 2026-09-03 that happened to five workers
in eleven minutes, the cause was outside this fleet entirely — the
provider stopped serving an old client build — and it fixed itself twenty
minutes later when the client auto-updated. Every one of those sessions
needed the same thing: to be told to keep going.

So the relay tells them, and the whole design question is how many times.
Unbounded retries against a wall are how a transient-failure recovery
becomes a spend loop, and the answer has three parts, all decided here.

**Whether to try at all** comes from the failure, not from a counter. The
shared signature list says whether re-running the turn could possibly
succeed: a capacity refusal or a dead client build, yes; an exhausted
quota or rejected credentials, never — no number of attempts moves those,
so they get zero and the report names the person who can act.

**How long to wait** grows with each attempt: one minute, then five, then
fifteen, measured from the most recent observed turn end. A provider that
just refused is likely to refuse again immediately, and the fifteen-minute
attempt is what happened to catch the real fix in the observed incident.

**What counts as an attempt** is the part with no new storage. A resume is
counted when its event is newer than the session's last tool call, which
is precisely the test the spec asks for: a resume that produced real work
pushes ``last_tool_call_at`` past its own event and the budget resets,
because a session that got something done and then hit the vendor again is
not the same stuck session; a resume that died seconds after injection
leaves the last tool call behind it and counts against the same three.

Two things this deliberately does not do. It never proposes resuming a
session inside an unreturned tool call — that turn is executing, and a
resume would be a second turn on the same conversation. And it never
spends the last attempt silently: when the budget is gone the row stays,
naming the seat as the next actor, because a worker nobody is coming for
must not look like one being handled.

Deciding lives apart from acting on purpose. The fleet report reads these
states to render them and changes nothing; the relay sweep in
``session_vendor_error_resume`` acts only on the ones marked ``due``. One
computation, so the report and the sweep cannot disagree about who is
being recovered.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from yoke_contracts.session_control.vendor_error_signatures import (
    classify_vendor_error,
)
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.session_activity_state import (
    OPEN_TOOL_CALL_COLUMN,
    open_tool_call_select,
)
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
    utc_now,
)
from yoke_core.domain.session_native_turn_end import (
    EVENT_SESSION_TURN_END_OBSERVED,
)


#: Event recording one resume the sweep requested, and the installed
#: client version the resumed turn runs on. Counting these is the budget.
EVENT_SESSION_VENDOR_ERROR_RESUMED = "HarnessSessionVendorErrorResumed"

#: How long after the observed turn end each successive attempt waits.
#: Its length is the budget: three entries, three attempts, then the seat.
RESUME_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 900)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _event_context(raw: Any) -> Mapping[str, Any]:
    """The context of one queried event row, or an empty mapping.

    A row whose envelope will not parse is not evidence, so it yields
    nothing rather than raising: one malformed row must not stop every
    other session on the machine from being recovered.
    """
    envelope: Any = raw
    if isinstance(envelope, str):
        try:
            envelope = json_helper.loads_text(envelope)
        except (TypeError, ValueError):
            return {}
    if not isinstance(envelope, Mapping):
        return {}
    context = envelope.get("context")
    return context if isinstance(context, Mapping) else {}


def _observed_turn_end(conn: Any, session_id: str) -> Mapping[str, Any]:
    """The newest recorded turn-end observation for one session."""
    marker = _p(conn)
    row = conn.execute(
        "SELECT created_at,envelope FROM events "
        f"WHERE event_name={marker} AND session_id={marker} "
        "ORDER BY created_at DESC LIMIT 1",
        (EVENT_SESSION_TURN_END_OBSERVED, session_id),
    ).fetchone()
    if row is None:
        return {}
    entry = row_dict(row)
    return {
        "recorded_at": str(entry.get("created_at") or ""),
        **_event_context(entry.get("envelope")),
    }


def _resumes_since(conn: Any, session_id: str, *, since: str) -> int:
    """How many resumes this session has had that produced no tool call.

    ``since`` is the session's own last tool call, and nothing else may be
    substituted for it. Counting from there is what makes the budget
    self-resetting without storing a counter: work done after a resume
    moves that stamp past the resume's event. Counting from the newest
    turn-end observation instead would reset the budget every time the
    provider refused again, which is precisely the unbounded retry this
    exists to bound. An empty ``since`` is a session that has never run a
    tool, so every resume it has ever had still counts.
    """
    marker = _p(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS attempts FROM events "
        f"WHERE event_name={marker} AND session_id={marker} "
        f"AND created_at>{marker}",
        (EVENT_SESSION_VENDOR_ERROR_RESUMED, session_id, since),
    ).fetchone()
    return int(row_dict(row).get("attempts") or 0) if row is not None else 0


def _candidate_sessions(
    conn: Any,
    *,
    machine_id: str | None,
    projects: Sequence[int],
) -> List[Dict[str, Any]]:
    """Live sessions in scope that have a turn end worth examining.

    The relay names its own machine, because it may only resume sessions
    it hosts. The fleet report names none: a steerer's scope is a project,
    and a worker stopped on some other machine is exactly the one whose
    silence would otherwise go unexplained.

    The ``EXISTS`` clause is what keeps this cheap on a healthy machine:
    a session with no recorded turn-end observation newer than its own
    last tool call is excluded in SQL, so the per-session reads below run
    only for the handful of sessions actually stopped. The stamp
    comparison there is a text one and so only approximate within a
    second, which is why the decision re-checks it as parsed instants —
    the coarse test is a filter, not the answer.
    """
    marker = _p(conn)
    project_slots = ",".join(marker for _ in projects)
    open_call = open_tool_call_select(conn, session_alias="hs")
    on_machine = f"hs.machine_id={marker} AND " if machine_id else ""
    rows = conn.execute(
        "SELECT hs.session_id,hs.project_id,hs.machine_id,hs.executor_surface,"
        "hs.executor_version,hs.last_tool_call_at,hs.turn_posture"
        f"{open_call} "
        "FROM harness_sessions hs "
        f"WHERE {on_machine}hs.ended_at IS NULL "
        f"AND hs.terminated_at IS NULL AND hs.project_id IN ({project_slots}) "
        "AND EXISTS (SELECT 1 FROM events e "
        f"WHERE e.session_id=hs.session_id AND e.event_name={marker} "
        "AND e.created_at>COALESCE(hs.last_tool_call_at,'')) "
        "ORDER BY hs.session_id",
        (
            *((machine_id,) if machine_id else ()),
            *projects,
            EVENT_SESSION_TURN_END_OBSERVED,
        ),
    ).fetchall()
    return [row_dict(raw) for raw in rows]


def _decision(
    row: Mapping[str, Any],
    observation: Mapping[str, Any],
    attempts: int,
    *,
    now: datetime,
) -> Dict[str, Any] | None:
    """Whether this session is owed a resume now, or why it is not.

    Returns ``None`` when the session has no vendor-ended turn to recover
    at all — the ordinary case for a healthy session, and not a finding.
    Every other answer is a named state the fleet report can render, so a
    session waiting on its backoff and one nobody is coming for never read
    alike.
    """
    error_message = str(observation.get("error_message") or "")
    if not error_message:
        return None
    observed_at = parse_timestamp(
        str(observation.get("observed_at") or "")
    ) or parse_timestamp(str(observation.get("recorded_at") or ""))
    if observed_at is None:
        return None
    signature = classify_vendor_error(
        observation.get("codex_error_info"),
        error_message,
    )
    state: Dict[str, Any] = {
        "session_id": str(row.get("session_id") or ""),
        "project_id": row.get("project_id"),
        "machine_id": str(row.get("machine_id") or ""),
        "executor_surface": str(row.get("executor_surface") or ""),
        "executor_version": str(row.get("executor_version") or ""),
        "signature_id": signature.signature_id,
        "error_message": error_message,
        "observed_at": timestamp(observed_at),
        "attempts": attempts,
        "budget": len(RESUME_BACKOFF_SECONDS) if signature.retryable else 0,
    }
    if not signature.retryable:
        # No attempt can move this failure, so none is made and the row
        # says so from the first poll rather than after three wasted tries.
        return {**state, "status": "seat_required", "reason": signature.summary}
    if attempts >= len(RESUME_BACKOFF_SECONDS):
        return {**state, "status": "budget_spent", "reason": signature.summary}
    if row.get(OPEN_TOOL_CALL_COLUMN):
        # The turn is executing. Whatever ended the previous one, this
        # session is working now and a resume would fork its conversation.
        return {
            **state,
            "status": "turn_in_flight",
            "reason": "recipient is inside an unreturned tool call",
            "in_flight_since": str(row.get(OPEN_TOOL_CALL_COLUMN) or ""),
        }
    due_at = observed_at + timedelta(seconds=RESUME_BACKOFF_SECONDS[attempts])
    state["due_at"] = timestamp(due_at)
    if due_at > now:
        return {**state, "status": "waiting_backoff", "reason": signature.summary}
    return {**state, "status": "due", "reason": signature.summary}


def vendor_error_states(
    conn: Any,
    *,
    authorized_projects: Iterable[int],
    machine_id: str | None = None,
    now: datetime | None = None,
) -> List[Dict[str, Any]]:
    """Every live session in scope whose last turn the model provider ended.

    One row per session, each carrying its named status — ``due``,
    ``waiting_backoff``, ``turn_in_flight``, ``budget_spent``, or
    ``seat_required``. The resume sweep acts on ``due``; the fleet report
    renders all of them, which is why the states are computed here once
    rather than twice with two chances to disagree.

    ``machine_id`` narrows the scope to one machine's own sessions, which
    is what the relay must do before resuming anything; the report leaves
    it out and sees the whole project.
    """
    current = now or utc_now()
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    if not projects:
        return []
    states: List[Dict[str, Any]] = []
    for row in _candidate_sessions(conn, machine_id=machine_id, projects=projects):
        session_id = str(row.get("session_id") or "")
        observation = _observed_turn_end(conn, session_id)
        if not observation:
            continue
        acted = str(row.get("last_tool_call_at") or "")
        recorded_at = str(observation.get("recorded_at") or "")
        if acted and recorded_at and acted >= recorded_at:
            # The session has run a tool since its turn end was recorded,
            # so whatever that observation described is over and done.
            continue
        decision = _decision(
            row,
            observation,
            _resumes_since(conn, session_id, since=acted),
            now=current,
        )
        if decision is not None:
            states.append(decision)
    return states


__all__ = [
    "EVENT_SESSION_VENDOR_ERROR_RESUMED",
    "RESUME_BACKOFF_SECONDS",
    "vendor_error_states",
]
