"""A host-contention handoff is an open QA obligation, never a review verdict."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from yoke_core.domain.db_helpers import instant_parameter, utc_now, query_one
from yoke_core.domain.qa_plan_execution_store import marker, select_plan_execution
from yoke_core.domain.qa_host_turns import record_host_wait


def submit_host_wait(
    conn: Any,
    execution: dict,
    *,
    bundle_id: str,
    bundle_digest: str,
    machine: str,
    rationale: str,
) -> dict:
    """Retain the attempt as history, then queue a fresh capture on the same target."""
    from yoke_core.domain.coordination_claims import active_claim, get_claim, release
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.host_control_runner import load_test_machine_contract
    from yoke_core.domain.qa_plan_review import QaPlanReviewError
    from yoke_core.domain.qa_host_turns import lock_host_turn

    p = marker(conn)
    bundle = query_one(
        conn,
        f"SELECT * FROM qa_plan_review_bundles WHERE id={p} AND execution_id={p}",
        (bundle_id, str(execution["id"])),
    )
    if (
        bundle is None
        or bundle["bundle_digest"] != bundle_digest
        or bundle["state"] != "pending"
    ):
        raise QaPlanReviewError(
            "host_wait_bundle_invalid: use the current pending review bundle"
        )
    if execution["state"] != "awaiting_agent_review":
        raise QaPlanReviewError(
            "host_wait_execution_invalid: submit only an awaiting mission"
        )
    if query_one(
        conn, f"SELECT 1 FROM qa_plan_review_verdicts WHERE bundle_id={p}", (bundle_id,)
    ):
        raise QaPlanReviewError(
            "host_wait_already_reviewed: a judged bundle cannot become waiting"
        )
    roster = execution["roster"]
    if not any(case.get("runner_id") == "agent_mission" for case in roster):
        raise QaPlanReviewError(
            "host_wait_requires_mission: deterministic captures cannot declare this hold"
        )
    load_test_machine_contract(conn, project=str(roster[0]["project"]), machine=machine)
    target = host_claim_target(machine)
    targets = [target]
    if execution.get("machine_lease_id") is not None:
        targets.append(get_claim(conn, int(execution["machine_lease_id"])).target)
    for candidate in sorted(targets, key=lambda value: str(value.machine_id)):
        lock_host_turn(conn, candidate)
    held = active_claim(conn, target)
    if held is None or held.session_id == execution["session_id"]:
        raise QaPlanReviewError(
            "host_wait_not_contended: the named host is free or yours; resume the walk"
        )
    stored_now = instant_parameter(conn, utc_now())
    # No verdict or decision request is created. The completed bundle preserves
    # its original capture and the reason this attempt could not finish.
    conn.execute(
        f"UPDATE qa_plan_review_bundles SET state='completed',reviewed_at={p} WHERE id={p}",
        (stored_now, bundle_id),
    )
    conn.execute(
        f"UPDATE qa_plan_executions SET state='completed',completed_at={p},"
        f"release_reason={p},machine_lease_id=NULL WHERE id={p}",
        (
            stored_now,
            "blocked-on-host:" + machine + ": " + rationale,
            str(execution["id"]),
        ),
    )
    stored = query_one(
        conn, f"SELECT * FROM qa_plan_executions WHERE id={p}", (str(execution["id"]),)
    )
    assert stored is not None
    # Clone immutable subject, roster and target; execution_order is generated
    # by the existing owner. A new capture gets its own bundle and run identities.
    values = dict(stored)
    values.pop("execution_order", None)
    values.update(
        id=str(uuid4()),
        cursor_ordinal=0,
        state="active",
        completed_at=None,
        release_reason=None,
        continues_execution_id=None,
        created_at=stored_now,
        heartbeat_at=stored_now,
    )
    columns = list(values)
    conn.execute(
        f"INSERT INTO qa_plan_executions({','.join(columns)}) VALUES({','.join([p] * len(columns))})",
        tuple(values[column] for column in columns),
    )
    fresh = select_plan_execution(conn, str(values["id"]), lock=False)
    result = record_host_wait(
        conn, fresh, machine=machine, rationale=rationale, commit=False
    )
    if execution.get("machine_lease_id") is not None:
        release(
            conn,
            int(execution["machine_lease_id"]),
            "mission-blocked-on-host",
            commit=False,
        )
    conn.commit()
    result.update(bundle_id=bundle_id, submission="waiting", verdicts=[])
    return result
