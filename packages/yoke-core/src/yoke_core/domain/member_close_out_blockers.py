"""Stable identities for what holds a delivery-cleared member short of done.

A close-out refusal's text carries each blocker's live status, so it changes
whenever a blocker moves without the set of blockers changing. The owner's
notice is keyed on these identities instead: a closure dependency by its
blocker ref, a target-qualified plan credit by plan and target, and any
other refusal by a digest of its text. Statuses and prose stay out.
"""

from __future__ import annotations

import hashlib
from typing import Any

from yoke_core.domain.closure_status_gate import evaluate as evaluate_closure
from yoke_core.domain.schema_common import _table_exists

CLOSURE = "closure"
PLAN = "plan"
REFUSED = "refused"

#: Separates a notice's base key from the blocker set it announced.
BLOCKED_SEPARATOR = ":blocked:"


def refusal_token(text: str) -> str:
    """A refusal with no structured identity, named by its text's digest."""
    return f"{REFUSED}:{hashlib.sha256(str(text).encode()).hexdigest()[:12]}"


def closure_blocker_refs(conn: Any, item_id: int) -> tuple[str, ...]:
    """Every blocker ref a closure gate on this item still waits on."""
    from yoke_core.domain.check_hard_blocks import evaluate_blockers
    from yoke_core.domain.dependency_types import GatePoint

    if not _table_exists(conn, "item_dependencies"):
        return ()
    lines = evaluate_blockers(
        int(item_id), gate_filter=GatePoint.CLOSURE.value, conn=conn
    )
    return tuple(
        sorted({parts[1] for line in lines if len(parts := line.split("|")) > 1})
    )


def owed_plan_targets(conn: Any, item_id: int) -> tuple[str, ...]:
    """Every ``plan@target`` credit the done gate still owes this item."""
    from yoke_core.domain.deployment_qa_plan_credit import PLAN_GROUP_QA_KIND
    from yoke_core.domain.qa_item_obligation_queries import unsatisfied_blocking

    rows = unsatisfied_blocking(conn, item_id=int(item_id), target_status="done").rows
    return tuple(
        sorted(
            {
                f"{row.get('plan_id')}@{row.get('target_env') or '-'}"
                for row in rows
                if row.get("qa_kind") == PLAN_GROUP_QA_KIND
            }
        )
    )


def blocker_identities(conn: Any, *, item_id: int, refusal: str) -> tuple[str, ...]:
    """The sorted identities of every blocker that holds this close-out.

    A refusal that is the closure gate's own text adds nothing beyond its
    dependency refs; any other refusal adds its digest.
    """
    refs = closure_blocker_refs(conn, int(item_id))
    identities = [f"{CLOSURE}:{ref}" for ref in refs]
    identities += [f"{PLAN}:{pair}" for pair in owed_plan_targets(conn, int(item_id))]
    if refusal:
        closure = evaluate_closure(item_id=int(item_id), conn=conn) if refs else None
        if closure is None or str(closure.get("error") or "") != refusal:
            identities.append(refusal_token(refusal))
    return tuple(sorted(identities))


def blocked_key(base: str, blockers: tuple[str, ...]) -> str:
    """The notice key for one blocker set: its sorted identities, readable."""
    if not blockers:
        return base
    return f"{base}{BLOCKED_SEPARATOR}{','.join(sorted(blockers))}"


def blocker_set_announced(
    conn: Any, *, prefix: str, blockers: tuple[str, ...]
) -> bool:
    """Whether one notice under ``prefix`` already named every one of ``blockers``.

    ``prefix`` spans every run's notice for one member, so a new or takeover
    run re-announces nothing its owner was already told. The owner was told
    each of them, and a blocker that cleared since is reported by its own
    notice (:mod:`dependency_satisfied_notice`), so a set that adds no
    blocker wakes nobody. An empty set is announced by any earlier notice
    that named no blocker.
    """
    if not _table_exists(conn, "session_messages"):
        return False
    rows = conn.execute(
        "SELECT idempotency_key FROM session_messages WHERE idempotency_key LIKE %s",
        (prefix + "%",),
    ).fetchall()
    wanted = set(blockers)
    for row in rows:
        key = str(row[0])
        if not key.startswith(prefix):
            continue
        _run, separator, announced = key[len(prefix):].partition(BLOCKED_SEPARATOR)
        if not separator:
            if not wanted:
                return True
            continue
        if wanted and wanted <= set(announced.split(",")):
            return True
    return False


__all__ = [
    "BLOCKED_SEPARATOR",
    "blocked_key",
    "blocker_identities",
    "blocker_set_announced",
    "closure_blocker_refs",
    "owed_plan_targets",
    "refusal_token",
]
