"""Rebind QA evidence when an environment declaration, not the target, moved.

A settings write can change the execution-target digest without changing
which environment row or subject the case ran against. The existing
snapshot reuse, retract, and supersession guards correctly refuse to
launder that evidence onto a different target. This module is the path
those guards do not cover: the same resolved host, whether the labels
still name the same identity or the endpoints already match that host.

Rebinding is not re-verifying. A different environment, deployment, or
subject still needs a fresh execution or sanctioned retirement. So does a
repointed host on the SAME row: identity cannot see that, so the rebind
refuses when resolved endpoint authority changes, stores the previous
target JSON, and reports the endpoint delta it did evaluate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import iso8601_now, query_one
from yoke_core.domain.qa_events import emit_qa_requirement_event
from yoke_core.domain.qa_execution_environment_target import canonical_target, target_digest
from yoke_core.domain.qa_requirement_rebind_endpoint_delta import (
    endpoint_delta,
    stale_label_rebind_applies,
    summarize_endpoint_delta,
)
from yoke_core.domain.qa_requirement_rebind_identity import (
    REBIND_RECIPE,
    QaRebindError,
    _live_target,
    declaration_correction_applies,
    different_target_reuse_recovery,
    identity_mismatch_message,
    same_environment_identity,
)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_object(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _rebind_payload(
    *,
    requirement_id: int,
    from_digest: str,
    to_digest: str,
    rebound_at: Any,
    rebind_rationale: Any,
    already_current: bool,
    from_target: Mapping[str, Any] | None,
    delta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "requirement_id": int(requirement_id),
        "from_digest": from_digest,
        "to_digest": to_digest,
        "rebound_at": rebound_at,
        "rebind_rationale": rebind_rationale,
        "already_current": already_current,
        "from_target": dict(from_target) if from_target else None,
        "endpoint_delta": dict(delta) if delta else None,
    }


def rebind_requirement(
    conn: Any,
    *,
    requirement_id: int,
    rationale: str,
    actor_id: int | None = None,
    db_path: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Point one requirement at the live declaration of its own environment."""
    rationale = str(rationale or "").strip()
    if not rationale:
        raise QaRebindError(
            "rebind requires a rationale explaining why the stored evidence "
            "still answers the live declaration of the same environment"
        )
    row = query_one(
        conn,
        "SELECT id,item_id,epic_id,task_num,deployment_run_id,plan_id,"
        "qa_kind,qa_phase,execution_target_json,execution_target_digest,"
        "rebound_at,rebound_from_digest,rebound_from_target_json,"
        "rebind_endpoint_delta_json,rebind_rationale,rebind_actor_id "
        "FROM qa_requirements WHERE id=%s",
        (int(requirement_id),),
    )
    if row is None:
        raise LookupError(f"requirement {requirement_id} not found")
    try:
        stored = json.loads(str(row["execution_target_json"] or ""))
    except (TypeError, ValueError) as exc:
        raise QaRebindError(
            f"requirement {requirement_id} has unreadable target evidence; "
            "preserve it and use sanctioned retirement or supersession"
        ) from exc
    if not isinstance(stored, dict):
        raise QaRebindError(
            f"requirement {requirement_id} has no object execution target; "
            "start a fresh execution or use sanctioned retirement or "
            "supersession"
        )
    live, environment_id, resolved_from = _live_target(
        conn, stored, plan_id=_int_or_none(row["plan_id"])
    )
    old_digest = str(row["execution_target_digest"] or "")
    new_json = canonical_target(live)
    new_digest = target_digest(live)
    delta = endpoint_delta(stored, live)
    if old_digest == new_digest:
        return _rebind_payload(
            requirement_id=int(requirement_id),
            from_digest=old_digest,
            to_digest=new_digest,
            rebound_at=row["rebound_at"],
            rebind_rationale=row["rebind_rationale"],
            already_current=True,
            from_target=_json_object(row["rebound_from_target_json"]),
            delta=_json_object(row["rebind_endpoint_delta_json"]) or delta,
        )
    if not (
        same_environment_identity(stored, live)
        or stale_label_rebind_applies(stored, live)
    ):
        raise QaRebindError(
            identity_mismatch_message(
                stored,
                live,
                environment_id=environment_id,
                resolved_from=resolved_from,
                requirement_id=int(requirement_id),
            )
        )
    if delta["authority_changed"]:
        raise QaRebindError(
            f"requirement {requirement_id} would move resolved host authority "
            f"({summarize_endpoint_delta(delta)}). Identity is the same row; "
            "the stored verdict cannot be shown to still answer a different "
            "host. Start a fresh deployment/plan execution or use sanctioned "
            "retirement or supersession; rebinding is not re-verifying"
        )
    now = iso8601_now()
    from_target_json = canonical_target(stored)
    delta_json = json.dumps(delta, sort_keys=True, separators=(",", ":"))
    conn.execute(
        "UPDATE qa_requirements SET execution_target_json=%s,"
        "execution_target_digest=%s,rebound_at=%s,rebound_from_digest=%s,"
        "rebound_from_target_json=%s,rebind_endpoint_delta_json=%s,"
        "rebind_rationale=%s,rebind_actor_id=%s WHERE id=%s",
        (
            new_json,
            new_digest,
            now,
            old_digest,
            from_target_json,
            delta_json,
            rationale,
            actor_id,
            int(requirement_id),
        ),
    )
    if commit:
        conn.commit()
    emit_qa_requirement_event(
        conn,
        db_path=db_path,
        event_name="QARequirementTargetRebound",
        requirement_id=int(requirement_id),
        qa_kind=str(row["qa_kind"] or ""),
        qa_phase=str(row["qa_phase"] or ""),
        rationale=rationale,
        target_row=row,
        extra_detail={
            "from_digest": old_digest,
            "to_digest": new_digest,
            "endpoint_delta": delta,
        },
    )
    return _rebind_payload(
        requirement_id=int(requirement_id),
        from_digest=old_digest,
        to_digest=new_digest,
        rebound_at=now,
        rebind_rationale=rationale,
        already_current=False,
        from_target=stored,
        delta=delta,
    )


__all__ = [
    "REBIND_RECIPE",
    "QaRebindError",
    "declaration_correction_applies",
    "different_target_reuse_recovery",
    "rebind_requirement",
    "same_environment_identity",
]
