"""Freeze release candidate membership immediately before run execution.

A membership row with no stored requirement selection is one admission
derived and deliberately did not keep: the answer to "what does this item
still owe" can change between that admission and this freeze -- a window
that has run to twenty minutes in practice -- so the list is derived here
instead, and written back concrete. An operator's stored selection is
frozen exactly as given.

Writing the derived list back is what keeps a retry honest. A retry copies
its predecessor's member rows verbatim, so once a run has frozen, every one
of its rows carries a concrete list and the retry's own freeze takes it as
given and reproduces the same snapshot. The only retry that inherits no
list is a retry of a run that never froze, which has no acceptance contract
to preserve.
"""

from __future__ import annotations

from yoke_core.domain.schema_read_scope import composition_operation
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.db_helpers import instant_parameter, utc_now

import json
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_work import record_carried_work
from yoke_core.domain.deployment_flow_delivery_custody import COLUMN, from_cell
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    snapshot_flow_requirements,
)
from yoke_core.domain.workflow_delivery_binding_validation import (
    COMPLETED_ITEM_STAGE_ID,
    attached_binding_runtime_state,
)
from yoke_core.domain.workflow_item_binding_validation import (
    has_workflow_pin_schema,
    read_pinned_items,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    WorkflowRuntime,
)


DELIVERY_INTENT_PROGRESS = "progress"
DELIVERY_INTENT_FINAL = "final"
DELIVERY_INTENTS = frozenset({DELIVERY_INTENT_PROGRESS, DELIVERY_INTENT_FINAL})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def normalize_delivery_intent(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    if normalized not in DELIVERY_INTENTS:
        raise ValueError(
            f"delivery_intent must be one of: {', '.join(sorted(DELIVERY_INTENTS))}"
        )
    return normalized


def default_delivery_intent(state: tuple[WorkflowRuntime, str] | None) -> str:
    """The intent a member with none stored delivers under, from its binding state."""
    if state is None:
        return DELIVERY_INTENT_FINAL
    runtime, status = state
    if status == COMPLETED_ITEM_STAGE_ID:
        return DELIVERY_INTENT_FINAL
    final_predecessors = {
        str(edge["from_stage_id"])
        for edge in runtime.definition["transitions"]
        if str(edge["to_stage_id"]) in runtime.terminal_stage_ids
    }
    if str(runtime.policies.get("delivery")) in (
        "continuous_slice_actions",
        WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
    ) and (
        runtime.implementation_has_started(str(status))
        and str(status) not in final_predecessors
    ):
        return DELIVERY_INTENT_PROGRESS
    return DELIVERY_INTENT_FINAL


def validate_delivery_intent(
    intent: str | None, state: tuple[WorkflowRuntime, str] | None
) -> str | None:
    """Validate an explicit progress intent against the item's binding state."""
    normalized = normalize_delivery_intent(intent)
    if normalized != DELIVERY_INTENT_PROGRESS:
        return normalized
    if state is None:
        raise ValueError("progress delivery requires a pinned item workflow")
    runtime, status = state
    if (
        str(runtime.policies.get("delivery"))
        not in (
            "continuous_slice_actions",
            WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
        )
        or str(status) in runtime.terminal_stage_ids
    ):
        raise ValueError(
            "progress delivery is available only to a nonterminal item whose "
            "effective workflow uses continuous_slice_actions"
        )
    return normalized


def requires_release_admission(conn: Any, run_id: str) -> bool:
    """Whether the run's flow takes delivery custody of carried items."""
    row = conn.execute(
        f"SELECT df.{COLUMN} FROM deployment_runs dr "
        f"JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id={_p(conn)}",
        (run_id,),
    ).fetchone()
    return row is not None and from_cell(_cell(row, COLUMN, 0))


def member_ids(conn: Any, run_id: str) -> tuple[int, ...]:
    rows = conn.execute(
        f"SELECT item_id FROM deployment_run_items WHERE run_id={_p(conn)} "
        "ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return tuple(int(_cell(row, "item_id", 0)) for row in rows)


def inherited_frozen_membership(conn: Any, run_id: str) -> bool:
    """Whether this run's members came from a run that already froze them.

    ``deployment_run_items.requirement_snapshot`` has exactly two writers:
    the freeze below, and the retry copy that carries a frozen run's members
    onto its replacement. A member holding one before this run has frozen
    anything can only have been inherited, which is the durable mark of a
    retry — and the reason its membership is read rather than derived again.
    """
    row = conn.execute(
        f"SELECT COUNT(*) FROM deployment_run_items WHERE run_id={_p(conn)} "
        "AND COALESCE(requirement_snapshot,'')<>''",
        (run_id,),
    ).fetchone()
    return bool(row and int(_cell(row, "count", 0) or 0))


#: Delivery policies whose items a release run delivers as members.
RELEASE_MEMBERSHIP_POLICIES = frozenset(
    {
        "release_stage",
        "continuous_slice_actions",
        "after_merge_action",
        WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
    }
)


def items_requiring_release_membership(
    conn: Any, item_ids: Iterable[int]
) -> frozenset[int]:
    """The items, of *item_ids*, a release run must deliver as members.

    One read answers the whole set. A done item owes no membership and could
    not take one: new admission of a terminal item is rejected, and its code
    reaches the environment under the run's pinned release lineage instead.
    Listing it would demand an attach that cannot happen.
    """
    from yoke_core.domain.workflow_delivery_binding_validation import (
        delivery_ready_for_stage,
    )

    required: set[int] = set()
    for item_id, pinned in read_pinned_items(conn, item_ids).items():
        runtime, status = pinned.require_runtime(conn, item_id), pinned.status
        if (
            status not in runtime.terminal_stage_ids
            and status not in ENGINE_TERMINAL_STAGE_IDS
            and str(runtime.policies.get("delivery")) in RELEASE_MEMBERSHIP_POLICIES
            and delivery_ready_for_stage(runtime, status)
        ):
            required.add(item_id)
    return frozenset(required)


@composition_operation
def freeze_run_composition(conn: Any, run_id: str) -> dict[str, Any]:
    """Freeze member intent/requirements and candidate evidence once."""
    if not requires_release_admission(conn, run_id):
        return {"run_id": run_id, "frozen_at": None}
    marker = _p(conn)
    row = conn.execute(
        f"SELECT dr.flow,dr.release_lineage,dr.composition_frozen_at,"
        f"dr.project_id,df.stages "
        f"FROM deployment_runs dr JOIN deployment_flows df ON df.id=dr.flow "
        f"WHERE dr.id={marker}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    frozen_at = _cell(row, "composition_frozen_at", 2)
    if frozen_at not in (None, ""):
        return {"run_id": run_id, "frozen_at": format_instant(frozen_at)}
    from yoke_core.domain.deployment_run_lineage_rebind import is_full_commit
    from yoke_core.domain.deployment_run_carried_membership_refusal import (
        carried_membership_refusal,
    )

    lineage = str(_cell(row, "release_lineage", 1) or "")
    if not is_full_commit(lineage):
        raise ValueError(
            f"deployment run {run_id!r} release_lineage must be a resolved full "
            "40-hex commit before release composition can freeze"
        )
    stages = json.loads(str(_cell(row, "stages", 4)))
    flow_snapshot = snapshot_flow_requirements(
        conn,
        flow_id=str(_cell(row, "flow", 0)),
        project_id=int(_cell(row, "project_id", 3)),
        stages=stages,
    )
    # Attribution must see the recorded source commits.
    record_bound_sources(conn, run_id)
    carried_work = record_carried_work(conn, run_id)
    from yoke_core.domain.deployment_run_unheld_candidates import (
        resolve_candidate_custody,
    )

    # Drift refuses: the driver already seeded its fixed member list.
    custody = resolve_candidate_custody(conn, run_id)
    if refusal := carried_membership_refusal(
        conn, run_id, carried_work=carried_work, custody=custody
    ):
        raise ValueError(refusal)
    from yoke_core.domain.deployment_member_run_coverage import (
        unclosable_final_member_refusal,
    )

    if refusal := unclosable_final_member_refusal(conn, run_id, custody=custody):
        raise ValueError(refusal)
    from yoke_core.domain.deployment_qa_admission_materialization import (
        ADMITTED_REQUIREMENT_CASE_PREFIX,
    )
    from yoke_core.domain.deployment_qa_direct_case_target import (
        UNBOUND_BEFORE_START_REPAIR,
    )

    unbound = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND method_id IS NOT NULL AND waived_at IS NULL "
        "AND (execution_target_digest IS NULL OR execution_target_digest='') "
        "AND (plan_case_key IS NULL OR plan_case_key NOT LIKE %s) "
        "ORDER BY id",
        (str(run_id), f"{ADMITTED_REQUIREMENT_CASE_PREFIX}%"),
    ).fetchall()
    if unbound:
        requirement_id = int(unbound[0]["id"])
        raise ValueError(
            f"QA requirement {requirement_id} "
            + UNBOUND_BEFORE_START_REPAIR.format(requirement_id=requirement_id)
        )
    _freeze_members(conn, run_id)
    frozen_at = parse_instant(utc_now())
    conn.execute(
        f"UPDATE deployment_runs SET composition_frozen_at={marker},"
        f"requirement_snapshot={marker} WHERE id={marker}",
        (
            instant_parameter(conn, frozen_at),
            flow_snapshot,
            run_id,
        ),
    )
    return {"run_id": run_id, "frozen_at": format_instant(frozen_at)}


def _freeze_members(conn: Any, run_id: str) -> None:
    """Write every member's concrete intent, selection and snapshot at once."""
    from yoke_core.domain.deployment_member_snapshot_write import (
        write_member_snapshots,
    )

    members = conn.execute(
        "SELECT item_id,delivery_intent,requirement_selection "
        "FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    # Preserve admission intent even if the item completed since admission.
    intents = {
        int(m["item_id"]): normalize_delivery_intent(m["delivery_intent"])
        for m in members
    }
    unset = [item_id for item_id, intent in intents.items() if intent is None]
    pinned = read_pinned_items(conn, unset) if has_workflow_pin_schema(conn) else None
    for item_id in unset:
        intents[item_id] = default_delivery_intent(
            None
            if pinned is None
            else attached_binding_runtime_state(conn, item_id, pinned.get(item_id))
        )
    # New obligations may arrive after admission; stored selections stay frozen.
    write_member_snapshots(
        conn,
        run_id,
        {int(m["item_id"]): m["requirement_selection"] for m in members},
        intents=intents,
    )
