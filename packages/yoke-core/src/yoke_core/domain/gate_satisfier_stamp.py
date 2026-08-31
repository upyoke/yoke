"""Durable record of which rung satisfied each of an item's obligations.

Before this surface existed, a gate that resolved a weaker satisfier had
nowhere to say so: the item reached its next status and the transcript
that knew *why* scrolled away. Two items that reached done through
completely different proofs — one merged with a green CI run, one merged
on a laptop with no remote at all — were indistinguishable afterwards.

``item_gate_satisfactions`` closes that. One row per
``(item_id, obligation)``, replaced whenever the obligation is
re-satisfied, carrying the rung id, the transition it answered, the
fact snapshot it resolved against, and a human sentence. The row is
readable from item detail and the matching event is queryable, so the
question "how did this item actually prove delivery?" has an answer that
outlives the session that produced it.

Stamping is best-effort at the storage layer and mandatory at the
decision layer: a gate resolves its ladder and refuses or proceeds on
that resolution regardless of whether the stamp lands, because a
recording failure must not become a second, quieter way to fail open.
An unwritable stamp surfaces as a WARN event, not as a passed gate.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.gate_satisfier_ladder import (
    LadderResolution,
    SatisfierLadder,
)


EVENT_STAMPED = "GateSatisfierRungStamped"
EVENT_REFUSED = "GateSatisfierRefused"

_EVENT_KIND = "lifecycle"
_EVENT_TYPE = "gate_satisfier"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_id() -> str:
    try:
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )
    except ImportError:  # pragma: no cover - defensive
        return ""
    try:
        return resolve_ambient_session_id() or ""
    except Exception:  # noqa: BLE001 - identity is context, never a blocker
        return ""


def record_rung(
    conn: Any,
    *,
    item_id: int,
    ladder: SatisfierLadder,
    resolution: LadderResolution,
    target_status: str = "",
    project: str = "",
) -> bool:
    """Persist and announce the rung that satisfied ``ladder`` for the item.

    Returns ``True`` when the row landed. A storage failure emits the
    event anyway so the resolution is still auditable, and returns
    ``False`` — callers proceed on the resolution, never on the stamp.
    """
    if not resolution.satisfied:
        raise ValueError(
            "record_rung needs a satisfied resolution; refuse through "
            "record_refusal instead"
        )
    rung = ladder.rung(resolution.rung_id)
    detail = rung.summary
    stored = _upsert(
        conn,
        item_id=item_id,
        obligation=ladder.obligation,
        rung_id=resolution.rung_id,
        target_status=target_status,
        detail=detail,
        facts=resolution.facts,
    )
    _emit(
        name=EVENT_STAMPED,
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=item_id,
        project=project,
        context={
            "obligation": ladder.obligation,
            "rung_id": resolution.rung_id,
            "rung_summary": detail,
            "target_status": target_status,
            "facts": resolution.facts,
            "rungs_rejected": [
                {
                    "rung_id": rejection.rung_id,
                    "missing_fact": rejection.missing_fact,
                    "verdict": rejection.verdict,
                }
                for rejection in resolution.rejected
            ],
            "stamp_recorded": stored,
        },
    )
    return stored


def record_refusal(
    conn: Any,
    *,
    item_id: Optional[int],
    ladder: SatisfierLadder,
    resolution: LadderResolution,
    target_status: str = "",
    project: str = "",
) -> None:
    """Announce that no rung was reachable, with the per-rung reasons."""
    _emit(
        name=EVENT_REFUSED,
        severity="WARN",
        outcome="blocked",
        conn=conn,
        item_id=item_id,
        project=project,
        context={
            "obligation": ladder.obligation,
            "target_status": target_status,
            "facts": resolution.facts,
            "rungs_rejected": [
                {
                    "rung_id": rejection.rung_id,
                    "missing_fact": rejection.missing_fact,
                    "verdict": rejection.verdict,
                    "detail": rejection.detail,
                }
                for rejection in resolution.rejected
            ],
        },
    )


def read_rungs(conn: Any, item_id: int) -> list[Dict[str, Any]]:
    """Return every recorded rung stamp for the item, obligation-ordered."""
    if not _table_exists(conn, "item_gate_satisfactions"):
        return []
    p = _p(conn)
    rows = conn.execute(
        "SELECT obligation, rung_id, target_status, detail, facts, "
        "recorded_at, recorded_by_session_id "
        f"FROM item_gate_satisfactions WHERE item_id = {p} "
        "ORDER BY obligation",
        (item_id,),
    ).fetchall()
    out: list[Dict[str, Any]] = []
    for row in rows:
        try:
            facts = json.loads(str(row[4] or "{}"))
        except ValueError:
            facts = {}
        out.append({
            "obligation": str(row[0]),
            "rung_id": str(row[1]),
            "target_status": str(row[2] or ""),
            "detail": str(row[3] or ""),
            "facts": facts,
            "recorded_at": row[5],
            "recorded_by_session_id": str(row[6] or ""),
        })
    return out


def _upsert(
    conn: Any,
    *,
    item_id: int,
    obligation: str,
    rung_id: str,
    target_status: str,
    detail: str,
    facts: Dict[str, str],
) -> bool:
    p = _p(conn)
    params = (
        rung_id,
        target_status,
        detail,
        json.dumps(facts, sort_keys=True),
        iso8601_now(),
        _session_id(),
        item_id,
        obligation,
    )
    try:
        updated = conn.execute(
            "UPDATE item_gate_satisfactions SET "
            f"rung_id = {p}, target_status = {p}, detail = {p}, "
            f"facts = {p}, recorded_at = {p}, recorded_by_session_id = {p} "
            f"WHERE item_id = {p} AND obligation = {p}",
            params,
        ).rowcount
        if not updated:
            conn.execute(
                "INSERT INTO item_gate_satisfactions "
                "(item_id, obligation, rung_id, target_status, detail, "
                "facts, recorded_at, recorded_by_session_id) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
                (item_id, obligation, *params[:6]),
            )
        conn.commit()
        return True
    except Exception:  # noqa: BLE001 - the event below carries the record
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def _emit(
    *,
    name: str,
    severity: str,
    outcome: str,
    conn: Any,
    item_id: Optional[int],
    project: str,
    context: Dict[str, Any],
) -> None:
    try:
        from yoke_core.domain.events import emit_event
    except ImportError:  # pragma: no cover - defensive
        return
    try:
        emit_event(
            name,
            event_kind=_EVENT_KIND,
            event_type=_EVENT_TYPE,
            source_type="system",
            session_id=_session_id(),
            severity=severity,
            outcome=outcome,
            project=project or "",
            item_id=str(item_id) if item_id is not None else None,
            context=context,
            conn=conn,
        )
    except Exception:  # noqa: BLE001 - telemetry never blocks a gate
        return


__all__ = [
    "EVENT_REFUSED",
    "EVENT_STAMPED",
    "read_rungs",
    "record_refusal",
    "record_rung",
]
