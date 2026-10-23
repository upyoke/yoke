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

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    build_execution_roster,
    canonical,
    roster_digest,
)


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
) -> PreparedRoster | dict[str, Any]:
    """Read the roster to freeze, or the answer that replaces starting one.

    The answer is a settled review to reprint or a completed execution that
    already covers the roster; neither writes.
    """
    from yoke_core.domain.qa_member_machine_partitions import member_machine_partition
    from yoke_core.domain.qa_plan_execution_roster import validate_roster_machine
    from yoke_core.domain.qa_plan_execution_target_snapshot import (
        execution_target_for_roster,
    )
    from yoke_core.domain.qa_plan_item_target_partition import item_target_partition
    from yoke_core.domain.qa_plan_settled_review import open_unsettled_roster

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

    def settle(source: list[dict[str, Any]]) -> tuple[Any, list[dict[str, Any]]]:
        return open_unsettled_roster(
            conn, source, item_id=item_id, transition_id=transition_id, **scope
        )

    item_remaining = None
    if item_id is None:
        reprint, roster = settle(roster)
    else:
        reprint, roster, item_remaining = item_target_partition(
            conn,
            roster,
            item_id=int(item_id),
            transition_id=str(transition_id),
            settle=settle,
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
    return PreparedRoster(
        roster, remaining, digest, execution_target, execution_target_digest
    )


__all__ = [
    "BeginInputsChanged",
    "PreparedRoster",
    "admit_current_roster",
    "admit_member",
    "begin_inputs",
    "prepare_roster",
]
