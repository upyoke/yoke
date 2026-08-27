"""Validation helpers for durable QA plan execution target snapshots."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


def execution_target_for_roster(
    roster: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Require every case to carry the same immutable execution target."""
    from yoke_core.domain.qa_plan_execution_store import (
        QaPlanExecutionStateError,
        canonical,
    )

    targets = [row.get("execution_target") for row in roster]
    digests = [str(row.get("execution_target_digest") or "") for row in roster]
    if (
        not targets
        or any(not isinstance(target, dict) for target in targets)
        or any(not digest for digest in digests)
    ):
        raise QaPlanExecutionStateError(
            "materialized QA roster lacks an execution target"
        )
    if len({canonical(target) for target in targets}) != 1 or len(set(digests)) != 1:
        raise QaPlanExecutionStateError(
            "materialized QA roster mixes execution targets"
        )
    target = dict(targets[0])
    from yoke_core.domain.qa_execution_environment_target import (
        require_runtime_target,
        target_digest,
    )

    if target_digest(target) != digests[0]:
        raise QaPlanExecutionStateError(
            "materialized QA roster target digest does not match"
        )
    require_runtime_target(target)
    return target, digests[0]


def decode_execution_target(
    execution: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Decode one persisted execution target without accepting non-objects."""
    raw_target = execution.get("execution_target_json")
    if not raw_target:
        return None
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

    try:
        target = json.loads(str(raw_target))
    except (TypeError, ValueError) as exc:
        raise QaPlanExecutionStateError(
            "QA plan execution contains an invalid target snapshot"
        ) from exc
    if not isinstance(target, dict):
        raise QaPlanExecutionStateError(
            "QA plan execution contains an invalid target snapshot"
        )
    from yoke_core.domain.qa_execution_environment_target import target_digest

    stored_digest = str(execution.get("execution_target_digest") or "")
    if not stored_digest or target_digest(target) != stored_digest:
        raise QaPlanExecutionStateError(
            "QA plan execution target snapshot digest does not match"
        )
    return target


def validate_execution_snapshot(
    execution: Mapping[str, Any],
    roster: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify the persisted roster and target remain one immutable snapshot."""
    from yoke_core.domain.qa_plan_execution_store import (
        QaPlanExecutionStateError,
        canonical,
        roster_digest,
    )

    if roster_digest(roster) != str(execution.get("roster_digest") or ""):
        raise QaPlanExecutionStateError(
            "QA plan execution roster snapshot digest does not match"
        )
    target = decode_execution_target(execution)
    if target is None:
        raise QaPlanExecutionStateError(
            "QA plan execution lacks an execution target"
        )
    roster_target, roster_target_digest = execution_target_for_roster(roster)
    if canonical(roster_target) != canonical(target) or roster_target_digest != str(
        execution.get("execution_target_digest") or ""
    ):
        raise QaPlanExecutionStateError(
            "QA plan execution roster target does not match its execution target"
        )
    return target


def rebind_unresolvable_targets(
    conn: Any,
    rows: Iterable[Mapping[str, Any]],
    *,
    execution_target: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return *rows* with any target the plan no longer resolves to replaced.

    A materialized requirement stores the execution target its plan resolved
    to when the requirement was written. Move the plan's environment binding —
    repoint a URL, rebuild a site — and that stored copy names a host that no
    longer answers. Reusing it aims a run at the wrong place; refusing to
    rematerialize leaves it aimed there forever, which is what an operator sees
    as the stale target surviving.

    The condition is decidable and narrow, and each clause earns its place:

    * the stored snapshot is internally consistent — its digest matches its own
      JSON — so a corrupt row reads as corruption rather than as a moved
      binding, and still refuses below;
    * that digest differs from the digest of the target the plan resolves to
      now, which is precisely "the binding moved since this row was written";
    * the requirement carries no run rows. Evidence is the whole reason the
      strict check exists: rebinding a requirement that already passed would
      re-attach a verdict earned against one host to a claim about another.
      A requirement with runs stays refused, and the operator retires or
      supersedes it deliberately.

    Rows that do not qualify are returned untouched, so the strict reuse check
    that runs after this still sees — and still refuses — everything it did
    before.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.qa_execution_environment_target import (
        canonical_target,
        target_digest,
    )

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    current_json = canonical_target(execution_target)
    current_digest = target_digest(execution_target)
    rebound: list[dict[str, Any]] = []
    for row in rows:
        updated = dict(row)
        rebound.append(updated)
        stored_digest = str(row["execution_target_digest"] or "")
        raw_target = row["execution_target_json"]
        if not raw_target or not stored_digest or stored_digest == current_digest:
            continue
        try:
            stored_target = json.loads(str(raw_target))
        except (TypeError, ValueError):
            continue
        if not isinstance(stored_target, dict):
            continue
        if target_digest(stored_target) != stored_digest:
            continue
        requirement_id = int(row["id"])
        if _requirement_has_runs(conn, requirement_id, marker):
            continue
        conn.execute(
            f"UPDATE qa_requirements SET execution_target_json={marker}, "
            f"execution_target_digest={marker} WHERE id={marker}",
            (current_json, current_digest, requirement_id),
        )
        updated["execution_target_json"] = current_json
        updated["execution_target_digest"] = current_digest
    return rebound


def _requirement_has_runs(conn: Any, requirement_id: int, marker: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM qa_runs WHERE qa_requirement_id={marker} LIMIT 1",
        (requirement_id,),
    ).fetchone()
    return row is not None


__all__ = [
    "decode_execution_target",
    "execution_target_for_roster",
    "rebind_unresolvable_targets",
    "validate_execution_snapshot",
]
