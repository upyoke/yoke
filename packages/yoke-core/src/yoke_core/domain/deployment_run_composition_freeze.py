"""Freeze release candidate membership immediately before run execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_carried_work import (
    derive_carried_work_safely,
    record_carried_work,
)
from yoke_core.domain.deployment_runs_schema import _run_field_available
from yoke_core.domain.deployment_flow_policy import RELEASE_POLICY_SCHEMA_VERSION
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    snapshot_flow_requirements,
    snapshot_member_requirements,
)
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.workflow_delivery_binding_validation import (
    COMPLETED_ITEM_STAGE_ID,
    attached_item_binding_runtime_state,
)
from yoke_core.domain.workflow_item_binding_validation import (
    item_binding_runtime_state,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    load_item_workflow_runtime,
)
from yoke_core.domain.project_identity import render_item_ref


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


def _default_delivery_intent(conn: Any, item_id: int) -> str:
    state = attached_item_binding_runtime_state(conn, int(item_id))
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


def validate_delivery_intent_for_item(
    conn: Any, item_id: int, intent: str | None
) -> str | None:
    """Validate an explicit progress intent against the pinned workflow."""
    normalized = normalize_delivery_intent(intent)
    if normalized != DELIVERY_INTENT_PROGRESS:
        return normalized
    state = item_binding_runtime_state(conn, int(item_id))
    if state is None:
        raise ValueError("progress delivery requires a pinned item workflow")
    runtime, status = state
    if str(runtime.policies.get("delivery")) not in (
        "continuous_slice_actions",
        WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
    ) or str(status) in runtime.terminal_stage_ids:
        raise ValueError(
            "progress delivery is available only to a nonterminal item whose "
            "effective workflow uses continuous_slice_actions"
        )
    return normalized


def requires_release_admission(conn: Any, run_id: str) -> bool:
    """Whether the run's flow uses the frozen release-policy contract."""
    if not _column_exists(conn, "deployment_flows", "definition_schema_version"):
        return False
    row = conn.execute(
        f"SELECT df.definition_schema_version FROM deployment_runs dr "
        f"JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id={_p(conn)}",
        (run_id,),
    ).fetchone()
    version = _cell(row, "definition_schema_version", 0) if row is not None else 1
    return row is not None and int(version or 1) >= RELEASE_POLICY_SCHEMA_VERSION


def _member_ids(conn: Any, run_id: str) -> tuple[int, ...]:
    rows = conn.execute(
        f"SELECT item_id FROM deployment_run_items WHERE run_id={_p(conn)} "
        "ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return tuple(int(_cell(row, "item_id", 0)) for row in rows)


def _item_requires_release_membership(conn: Any, item_id: int) -> bool:
    row = conn.execute(
        f"SELECT p.slug,i.deployment_flow,i.workflow_id,i.status FROM items i "
        f"JOIN projects p ON p.id=i.project_id WHERE i.id={_p(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return False
    project = str(_cell(row, "slug", 0))
    effective_flow = _cell(row, "deployment_flow", 1)
    if not effective_flow:
        from yoke_core.domain.workflow_project_defaults import get_delivery_default

        effective_flow = get_delivery_default(
            conn, project=project, workflow_id=str(_cell(row, "workflow_id", 2))
        )
    if not effective_flow:
        return False
    runtime = load_item_workflow_runtime(conn, int(item_id))
    status = str(_cell(row, "status", 3))
    if status in runtime.terminal_stage_ids or status in ENGINE_TERMINAL_STAGE_IDS:
        # A done item owes no membership and could not take one: new
        # admission of a terminal item is rejected, and its code reaches
        # the environment under this run's pinned release lineage
        # instead. Listing it would demand an attach that cannot happen.
        return False
    if str(runtime.policies.get("delivery")) not in {
        "release_stage",
        "continuous_slice_actions",
        "after_merge_action",
        WORKFLOW_DELIVERY_CONTINUOUS_SLICE_THEN_RELEASE,
    }:
        return False
    from yoke_core.domain.workflow_delivery_binding_validation import (
        delivery_ready_for_stage,
    )

    return delivery_ready_for_stage(runtime, str(status))


def carried_membership_refusal(
    conn: Any,
    run_id: str,
    *,
    carried_work: Mapping[str, Any] | None = None,
) -> str | None:
    """Return an actionable refusal for unresolved or omitted deliverable code."""
    if not requires_release_admission(conn, run_id):
        return None
    if not _column_exists(conn, "deployment_runs", "composition_resolution"):
        return None
    run = conn.execute(
        f"SELECT release_lineage,composition_resolution FROM deployment_runs "
        f"WHERE id={_p(conn)}",
        (run_id,),
    ).fetchone()
    if run is None:
        return f"deployment run {run_id!r} not found"
    lineage = str(_cell(run, "release_lineage", 0) or "").strip()
    resolution = str(_cell(run, "composition_resolution", 1) or "").strip()
    if not lineage:
        return None
    payload = dict(carried_work or derive_carried_work_safely(conn, run_id))
    derivation = payload.get("derivation") or {}
    reason = str(derivation.get("reason") or "unknown")
    if not bool(derivation.get("contents_known")):
        if resolution:
            return None
        return (
            f"deployment run {run_id!r} carried-code membership is {reason}; "
            "repair attribution or record composition_resolution before execution"
        )
    bare = [str(value) for value in payload.get("commits") or []]
    if bare and not resolution:
        return (
            f"deployment run {run_id!r} has {len(bare)} unattributed carried commit(s); "
            "record composition_resolution explaining their membership treatment"
        )
    members = set(_member_ids(conn, run_id))
    omitted = sorted(
        int(entry["item_id"])
        for entry in payload.get("items") or []
        if int(entry["item_id"]) not in members
        and _item_requires_release_membership(conn, int(entry["item_id"]))
    )
    if not omitted:
        return None
    labels = ", ".join(
        render_item_ref(conn, int(item_id)) for item_id in omitted
    )
    return (
        f"deployment run {run_id!r} omits delivery-ready carried work: {labels}; "
        "attach those members, or choose a candidate that excludes their code. "
        "An already-done item is never one of them: it cannot be newly "
        "admitted, and its code travels under the run's pinned release lineage"
    )


def _require_schema(conn: Any) -> None:
    missing: list[str] = []
    for column in (
        "artifact_identity",
        "composition_resolution",
        "composition_frozen_at",
        "requirement_snapshot",
    ):
        if not _run_field_available(conn, column):
            missing.append(f"deployment_runs.{column}")
    for column in (
        "delivery_intent",
        "requirement_selection",
        "requirement_snapshot",
    ):
        if not _column_exists(conn, "deployment_run_items", column):
            missing.append(f"deployment_run_items.{column}")
    if missing:
        raise RuntimeError(
            "deployment composition schema has not converged: "
            + ", ".join(missing)
            + "; apply the current additive schema before execution"
        )


def freeze_run_composition(conn: Any, run_id: str) -> dict[str, Any]:
    """Freeze member intent/requirements and candidate evidence once."""
    if not requires_release_admission(conn, run_id):
        return {"run_id": run_id, "frozen_at": "", "legacy": True}
    _require_schema(conn)
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
    frozen_at = str(_cell(row, "composition_frozen_at", 2) or "")
    if frozen_at:
        return {"run_id": run_id, "frozen_at": frozen_at}
    from yoke_core.domain.deployment_run_lineage_rebind import is_full_commit

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
    carried_work = record_carried_work(conn, run_id)
    if refusal := carried_membership_refusal(conn, run_id, carried_work=carried_work):
        raise ValueError(refusal)
    for item_id in _member_ids(conn, run_id):
        member = conn.execute(
            f"SELECT delivery_intent,requirement_selection "
            f"FROM deployment_run_items "
            f"WHERE run_id={marker} AND item_id={marker}",
            (run_id, item_id),
        ).fetchone()
        # Admission already validated an explicit intent.  Preserve that
        # established choice even when the attached item has since completed;
        # freeze is not a second admission against mutable item status.
        intent = normalize_delivery_intent(_cell(member, "delivery_intent", 0))
        intent = intent or _default_delivery_intent(conn, item_id)
        snapshot = snapshot_member_requirements(
            conn,
            run_id=run_id,
            item_id=item_id,
            selection_json=_cell(member, "requirement_selection", 1),
        )
        conn.execute(
            f"UPDATE deployment_run_items SET delivery_intent={marker},"
            f"requirement_snapshot={marker} "
            f"WHERE run_id={marker} AND item_id={marker}",
            (intent, snapshot, run_id, item_id),
        )
    from yoke_core.domain.db_helpers import iso8601_now

    frozen_at = iso8601_now()
    conn.execute(
        f"UPDATE deployment_runs SET composition_frozen_at={marker},"
        f"requirement_snapshot={marker} WHERE id={marker}",
        (frozen_at, flow_snapshot, run_id),
    )
    return {"run_id": run_id, "frozen_at": frozen_at}
