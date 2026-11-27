"""Read a QA execution's roster unlocked, then lock the run only to write it.

Beginning a deployment member's execution reads facts whose count grows with
the run's members and plan groups. Those reads run before the
``deployment_runs`` row lock. :func:`begin_inputs` fingerprints run facts,
excluding execution progress; :func:`admit_member` takes the lock and
compares that fingerprint again. Run changes repeat the reads unlocked
(:func:`admit_current_roster`); custody is checked under the run lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.qa_deployment_requirement_identity_schema import shared_group_id
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    build_execution_roster,
    canonical,
    roster_digest,
)
from yoke_core.domain.qa_walk_launch_required import require_scoped_walk_launch, require_walk_launch


class BeginInputsChanged(Exception):
    """A run fact read before the run lock changed before the lock was taken."""


def begin_inputs(
    conn: Any, run_id: str, stage: str | None, *, run_fingerprint: str | None = None
) -> str:
    """Fingerprint the run's QA facts; execution churn does not change admission."""
    from yoke_core.domain.deployment_run_qa_fingerprint import run_qa_fingerprint

    return run_fingerprint or run_qa_fingerprint(conn, str(run_id))


def admit_member(
    conn: Any,
    run_id: str,
    stage: str | None,
    member: int | None,
    inputs: str | None,
) -> bool:
    """Lock the run for ``member``; report whether ``inputs`` still hold.

    ``None`` inputs mean the caller already read under this lock, so there is
    nothing to compare. A stage-wide begin without a member locks the run alone.
    """
    from yoke_core.domain.deployment_runs_lock import lock_run
    from yoke_core.domain.qa_plan_execution_authority import lock_member_admission

    if member is None:
        lock_run(conn, str(run_id))
    else:
        lock_member_admission(conn, run_id, member)
    return inputs is None or begin_inputs(conn, run_id, stage) == inputs


def admit_current_roster(conn, run_id, stage, member, inputs, prepared, prepare):
    """Lock the run for this begin once its unlocked roster read still holds.

    A member's begin hands a change back to its router as
    :class:`BeginInputsChanged`, and the router reads again unlocked. A
    stage-wide begin releases the lock itself and reads again unlocked, at
    most ``RUN_READ_ATTEMPTS`` times, then refuses as ``run_busy``
    (``run_read_changed``). Returns the roster to write, or the answer that
    replaces starting one.
    """
    from yoke_core.domain.deployment_runs_lock import (
        RUN_READ_ATTEMPTS,
        DeploymentRunChanging,
    )

    for attempt in range(1, RUN_READ_ATTEMPTS + 1):
        if admit_member(conn, run_id, stage, member, inputs):
            return prepared
        if member is not None:
            raise BeginInputsChanged(run_id)
        # Every write before this commits, so the rollback releases only the lock.
        conn.rollback()
        if attempt == RUN_READ_ATTEMPTS:
            break
        inputs = begin_inputs(conn, run_id, stage)
        prepared = prepare()
        if not isinstance(prepared, PreparedRoster):
            return prepared
    raise DeploymentRunChanging(str(run_id))


@dataclass(frozen=True)
class PreparedRoster:
    """The roster an execution would freeze, read before the run lock."""

    roster: list[dict[str, Any]]
    remaining: int | None
    digest: str
    execution_target: dict[str, Any]
    execution_target_digest: str
    partition: str | None = None


def prepare_roster(
    conn: Any,
    *,
    item_id: int | None,
    transition_id: str | None,
    deployment_run_id: str | None,
    deployment_stage: str | None,
    deployment_member_item_id: int | None,
    expected_target: dict[str, Any] | None,
    expected_target_digest: str | None,
    plan: str | None,
    host_capability_kinds: Any,
    checkout_path: str | None,
    expected_branch: str | None,
    session_id: str,
    test_machine: str | None,
    requirement_id: int | None = None,
    partition: str | None = None,
    source_session_id: str | None = None,
) -> PreparedRoster | dict[str, Any]:
    """Read the roster to freeze, or the answer that replaces starting one.

    The answer is a settled review to reprint or a completed execution that
    already covers the roster; neither writes.
    """
    from yoke_core.domain.qa_plan_execution_roster import validate_roster_machine
    from yoke_core.domain.qa_plan_execution_target_snapshot import (
        execution_target_for_roster,
    )
    from yoke_core.domain.qa_plan_settled_review import open_unsettled_roster

    if partition is not None or (requirement_id is not None and (
        item_id is not None or deployment_stage is not None
    )) or _has_authored_order(conn, item_id, transition_id, deployment_run_id, deployment_stage):
        return _prepare_partition_roster(
            conn,
            item_id=item_id,
            transition_id=transition_id,
            deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage,
            deployment_member_item_id=deployment_member_item_id,
            expected_target=expected_target,
            expected_target_digest=expected_target_digest,
            plan=plan,
            host_capability_kinds=host_capability_kinds,
            checkout_path=checkout_path,
            expected_branch=expected_branch,
            session_id=session_id,
            test_machine=test_machine,
            requirement_id=requirement_id,
            partition=partition,
            source_session_id=source_session_id,
        )

    scope = dict(
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    roster = build_execution_roster(
        conn,
        item_id=item_id,
        transition_id=transition_id,
        **scope,
        execution_target_digest=expected_target_digest,
        plan=plan,
        **({"requirement_id": requirement_id} if requirement_id is not None else {}),
        host_capability_kinds=host_capability_kinds,
        checkout_path=checkout_path,
        expected_branch=expected_branch,
        session_id=session_id,
    )

    from yoke_core.domain.qa_member_machine_partitions import member_machine_partition
    from yoke_core.domain.qa_plan_item_target_partition import item_target_partition

    def settle(source):
        return open_unsettled_roster(
            conn, source, item_id=item_id, transition_id=transition_id, **scope
        )

    item_remaining = None
    if item_id is None:
        reprint, roster = settle(roster)
    else:
        reprint, roster, item_remaining = item_target_partition(
            conn, roster, item_id=int(item_id), transition_id=str(transition_id),
            settle=settle, session_id=session_id,
        )
    if reprint:
        return reprint
    roster, remaining, completed = member_machine_partition(
        conn, roster, **scope, test_machine=test_machine, session_id=session_id
    )
    if completed is not None:
        return {**completed, "remaining_requirement_count": remaining}
    remaining = item_remaining if remaining is None else remaining
    validate_roster_machine(conn, roster, test_machine)
    digest = roster_digest(roster)
    execution_target, execution_target_digest = execution_target_for_roster(roster)
    if expected_target is not None and canonical(execution_target) != canonical(
        expected_target
    ):
        raise QaPlanExecutionStateError(
            "materialized QA roster does not match the active deployment target"
        )
    require_scoped_walk_launch(
        conn, roster, session_id=session_id, execution_target_digest=execution_target_digest,
        group_id=shared_group_id(execution_target), item_id=item_id, transition_id=transition_id, **scope,
    )
    return PreparedRoster(
        roster, remaining, digest, execution_target, execution_target_digest
    )


def _has_authored_order(conn, item_id, transition, run_id, stage):
    from yoke_core.domain.qa_plan_execution_store import marker

    bind = marker(conn)
    subject = (
        f"item_id={bind} AND workflow_transition_id={bind}"
        if item_id is not None
        else f"deployment_run_id={bind} AND deployment_stage={bind}"
    )
    return bool(conn.execute(
        f"SELECT 1 FROM qa_requirements WHERE {subject} "
        "AND after_case_key IS NOT NULL AND retracted_at IS NULL LIMIT 1",
        (item_id, transition) if item_id is not None else (run_id, stage),
    ).fetchone())


def _prepare_partition_roster(
    conn,
    *,
    item_id,
    transition_id,
    deployment_run_id,
    deployment_stage,
    deployment_member_item_id,
    expected_target,
    expected_target_digest,
    plan,
    host_capability_kinds,
    checkout_path,
    expected_branch,
    session_id,
    test_machine,
    requirement_id,
    partition,
    source_session_id,
):
    from yoke_core.domain.qa_case_execution_context import get_case_execution_context
    from yoke_core.domain.qa_plan_execution_roster import validate_roster_machine
    from yoke_core.domain.qa_plan_execution_target_snapshot import execution_target_for_roster
    from yoke_core.domain.qa_plan_partition_custody import PartitionScope, partition_unavailable
    from yoke_core.domain.qa_plan_partitions import scoped_partition_views, select_partition

    scope = PartitionScope(
        item_id, transition_id, deployment_run_id, deployment_stage, deployment_member_item_id
    )
    roster = build_execution_roster(
        conn,
        item_id=item_id, transition_id=transition_id, deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage, deployment_member_item_id=deployment_member_item_id,
        execution_target_digest=expected_target_digest, plan=plan,
        checkout_path=checkout_path, expected_branch=expected_branch,
        session_id=source_session_id or session_id,
    )
    views = scoped_partition_views(conn, scope, roster)
    selected = select_partition(
        views, key=partition, session_id=session_id, requirement_id=requirement_id,
        allow_failed=True,
        stage_wide=scope.stage_wide,
    )
    if selected is None:
        from yoke_core.domain.qa_plan_settled_review import open_unsettled_roster

        for view in views:
            if not any(row["verdict_path"] == "agent" for row in view.partition.roster):
                continue
            reprint, _ = open_unsettled_roster(
                conn, view.partition.roster, item_id=item_id, transition_id=transition_id,
                deployment_run_id=deployment_run_id, deployment_stage=deployment_stage,
                deployment_member_item_id=deployment_member_item_id,
            )
            if reprint:
                return reprint
        if item_id is not None:
            raise QaPlanExecutionStateError(
                "qa_plan_roster_passed_at_candidate: every partition already passed. "
                "Read each partition with `yoke qa plan partitions` or the "
                "recorded results with `yoke qa requirement list`."
            )
        from yoke_core.domain.qa_plan_nothing_owed import nothing_owed

        raise nothing_owed(
            conn, roster_size=len(roster), deployment_run_id=deployment_run_id,
            deployment_stage=deployment_stage, deployment_member_item_id=deployment_member_item_id,
        )
    part = selected.partition
    if selected.holder is None and part.kind == "walk":
        require_walk_launch(conn, part.roster, session_id=session_id)
    if requirement_id is not None and len(part.roster) != 1:
        raise partition_unavailable(part.key, "must run its entire inherited chain")
    if part.kind == "lane" and requirement_id is None:
        requirement = part.roster[0]["requirement_id"]
        raise partition_unavailable(
            part.key, f"belongs to the source lane; run `yoke qa case run --requirement-id {requirement}`"
        )
    roster = [
        {
            **row, "ordinal": ordinal,
            **({"delegated_walk": source_session_id} if source_session_id else {}),
        }
        for ordinal, row in enumerate(part.roster)
    ]
    if selected.holder is None and host_capability_kinds is not None:
        for row in roster:
            get_case_execution_context(
                conn, requirement_id=row["requirement_id"],
                host_capability_kinds=host_capability_kinds,
                checkout_path=checkout_path, expected_branch=expected_branch,
                session_id=source_session_id or session_id,
            )
    validate_roster_machine(conn, roster, test_machine)
    target, digest = execution_target_for_roster(roster)
    if expected_target is not None and canonical(target) != canonical(expected_target):
        raise QaPlanExecutionStateError(
            "materialized QA roster does not match the active deployment target"
        )
    remaining = sum(
        len(view.partition.roster)
        for view in views if view is not selected and view.state != "passed"
    )
    return PreparedRoster(roster, remaining, roster_digest(roster), target, digest, part.key)


__all__ = [
    "BeginInputsChanged",
    "PreparedRoster",
    "admit_current_roster",
    "admit_member",
    "begin_inputs",
    "prepare_roster",
]
