"""Amend one workflow-posture key on an item after it was filed.

Posture is chosen when an item is filed — a verification plan or method, the
path-claims coverage knob, approval-on-done, deploy-after-merge.  Until this
surface existed that choice was final: an item filed without a verification
selection could not attach or materialize a QA case afterwards, because the
optional item-QA binding accepts only the plan or method named in
``items.workflow_posture``.  The only recovery was cancel-and-re-file, which
burns the item ref and loses every note the item had accumulated.

One operation covers every posture key.  The amendable roster is the pinned
definition's ``item_posture_allowlist`` — read from the item, never from
prose — and each key in the shared vocabulary declares in :data:`AMEND_GUARDS`
what changing it can strand.  A key the vocabulary gains without an entry
there refuses by name instead of silently inheriting "nothing to protect".
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Optional

from yoke_core.domain.dash_posture_read import marker, posture as read_posture
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_posture_amend_guards import (
    ItemPostureAmendError,
    guard_approval,
    guard_path_claims,
    guard_verification,
    requirement_ids,
)
from yoke_core.domain.item_posture_validation import (
    ItemPostureError,
    validate_item_posture,
)
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_definition_validation import ITEM_POSTURE_VALUES
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    load_item_workflow_runtime,
)


AMENDED_EVENT_NAME = "ItemWorkflowPostureAmended"
SUPERSEDED_RATIONALE = "Superseded by a workflow-posture amendment."

Guard = Callable[..., None]

# What each posture key leaves behind, and therefore what an amendment has to
# protect.  ``None`` declares a key that records nothing of its own, so the
# shared terminal-stage refusal is the whole guard.
AMEND_GUARDS: dict[str, Optional[Guard]] = {
    "approval": guard_approval,
    "approval_on_done": guard_approval,
    "deployment": None,
    "file_budget": None,
    "path_claims": guard_path_claims,
    "path_survey": None,
    "verification": guard_verification,
}

UNDECLARED_KEYS = sorted(set(ITEM_POSTURE_VALUES) - set(AMEND_GUARDS))


def _item_row(conn: Any, item_id: int) -> dict[str, Any]:
    placeholder = marker(conn)
    cursor = conn.execute(
        "SELECT id, project_id, status, workflow_posture FROM items "
        f"WHERE id = {placeholder}",
        (int(item_id),),
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError(f"item {item_id} does not exist")
    columns = [str(column[0]) for column in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


def _supersede_verification(
    conn: Any,
    *,
    item_id: int,
    previous: Mapping[str, Any],
) -> dict[str, list[int]]:
    """Retire the bindings the replaced verification selection left behind.

    The guard has already refused any requirement carrying a recorded run, so
    everything retired here is an unexecuted snapshot.  Waiving rather than
    deleting keeps the row visible as history while taking it out of every
    blocking read.
    """
    waived = requirement_ids(
        conn,
        item_id=int(item_id),
        verification=previous,
        with_runs=False,
    )
    placeholder = marker(conn)
    now = iso8601_now()
    for requirement_id in waived:
        conn.execute(
            f"UPDATE qa_requirements SET waived_at={placeholder}, "
            f"waiver_rationale={placeholder}, waiver_source={placeholder} "
            f"WHERE id={placeholder}",
            (now, SUPERSEDED_RATIONALE, "system", requirement_id),
        )
    detached: list[int] = []
    plan_id = previous.get("plan_id")
    if plan_id is not None and _table_exists(conn, "qa_plan_item_attachments"):
        conn.execute(
            "DELETE FROM qa_plan_item_attachments "
            f"WHERE item_id={placeholder} AND transition_id={placeholder} "
            f"AND plan_id={placeholder}",
            (int(item_id), ITEM_POSTURE_VERIFICATION_TRANSITION, int(plan_id)),
        )
        detached.append(int(plan_id))
    return {"waived_requirement_ids": waived, "detached_plan_ids": detached}


def _emit_amended(
    conn: Any,
    *,
    item_id: int,
    project: str,
    session_id: str,
    context: dict[str, Any],
) -> Optional[str]:
    from yoke_core.domain.events import emit_event

    envelope = emit_event(
        AMENDED_EVENT_NAME,
        event_kind="workflow",
        event_type="item_posture_amendment",
        source_type="system",
        session_id=session_id,
        severity="INFO",
        outcome="completed",
        project=project,
        item_id=item_id,
        context=context,
        conn=conn,
        transactional=True,
    )
    return envelope.event_id if envelope.ok else None


def amend_item_posture(
    conn: Any,
    *,
    item_id: int,
    key: str,
    value: Any = None,
    clear: bool = False,
    reason: str,
    actor_id: Optional[int] = None,
    session_id: str = "",
    commit: bool = True,
) -> dict[str, Any]:
    """Set, replace, or clear one posture key on an already-filed item."""
    if not str(reason or "").strip():
        raise ItemPostureAmendError(
            "a posture amendment requires a non-empty reason; it is the only "
            "record of why the filed selection changed"
        )
    runtime = load_item_workflow_runtime(conn, int(item_id))
    item = _item_row(conn, int(item_id))
    before = read_posture(item)
    allowlist = [str(value) for value in runtime.policies["item_posture_allowlist"]]
    if key not in allowlist:
        raise ItemPostureAmendError(
            f"{runtime.workflow_id}@{runtime.version} does not allow posture "
            f"key {key!r}. Allowed on this item: {sorted(allowlist)}."
        )
    if key not in AMEND_GUARDS:
        raise ItemPostureAmendError(
            f"posture key {key!r} is unamendable: it has no declared "
            "amendment guard, so changing it could strand records nothing "
            "checks. Declare the key in "
            "yoke_core.domain.item_posture_amend.AMEND_GUARDS — with a guard "
            "when the selection leaves records behind, or None when it does "
            "not — and the amend surface covers it."
        )
    status = str(item["status"])
    if status in runtime.terminal_stage_ids or status in ENGINE_TERMINAL_STAGE_IDS:
        raise ItemPostureAmendError(
            f"item {item_id} is at terminal stage {status!r}; every posture "
            "gate has already run, so an amendment would change nothing. "
            "File the follow-on work as its own item."
        )
    after = dict(before)
    if clear:
        after.pop(key, None)
    else:
        after[key] = value
    try:
        normalized = validate_item_posture(
            conn,
            definition=runtime.definition,
            project_id=int(item["project_id"]),
            posture=after,
        )
    except (ItemPostureError, LookupError) as exc:
        raise ItemPostureAmendError(str(exc)) from exc
    if normalized == before:
        return {
            "changed": False,
            "item_id": int(item_id),
            "key": key,
            "before": dict(before),
            "after": dict(before),
            "waived_requirement_ids": [],
            "detached_plan_ids": [],
            "binding": None,
            "event_id": None,
        }

    guard = AMEND_GUARDS[key]
    if guard is not None:
        guard(conn, item_id=int(item_id), key=key, before=before, after=normalized)

    superseded: dict[str, list[int]] = {
        "waived_requirement_ids": [],
        "detached_plan_ids": [],
    }
    previous_verification = before.get("verification")
    if key == "verification" and isinstance(previous_verification, Mapping):
        superseded = _supersede_verification(
            conn,
            item_id=int(item_id),
            previous=previous_verification,
        )

    placeholder = marker(conn)
    conn.execute(
        f"UPDATE items SET workflow_posture={placeholder}, "
        f"updated_at={placeholder} WHERE id={placeholder}",
        (json.dumps(normalized, sort_keys=True), iso8601_now(), int(item_id)),
    )

    from yoke_core.domain.item_posture_bindings import bind_item_posture_selection

    binding = bind_item_posture_selection(
        conn,
        item_id=int(item_id),
        definition=runtime.definition,
        posture=normalized,
        actor_id=actor_id,
        commit=False,
    )
    event_id = _emit_amended(
        conn,
        item_id=int(item_id),
        project=str(item["project_id"]),
        session_id=session_id,
        context={
            "key": key,
            "reason": reason,
            "before": dict(before),
            "after": dict(normalized),
            **superseded,
        },
    )
    if commit:
        conn.commit()
    return {
        "changed": True,
        "item_id": int(item_id),
        "key": key,
        "before": dict(before),
        "after": dict(normalized),
        "binding": binding.get("verification"),
        "event_id": event_id,
        **superseded,
    }


__all__ = [
    "AMENDED_EVENT_NAME",
    "AMEND_GUARDS",
    "ItemPostureAmendError",
    "SUPERSEDED_RATIONALE",
    "UNDECLARED_KEYS",
    "amend_item_posture",
]
