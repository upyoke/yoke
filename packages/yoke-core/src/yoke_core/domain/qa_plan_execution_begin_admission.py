"""Read a QA execution's roster unlocked, then lock the run only to write it.

Beginning a deployment member's execution reads facts whose count grows with
the run's members and plan groups. Those reads run before the
``deployment_runs`` row lock. :func:`begin_inputs` digests what they depended
on first; :func:`admit_member` takes the lock and compares the digest again,
so a change committed in between is caught and the reads repeat under it.
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


def _executions_digest(conn: Any, run_id: str, stage: str | None) -> str:
    row = conn.execute(
        "SELECT md5(COALESCE(string_agg(id||':'||state||':'||cursor_ordinal,"
        "'|' ORDER BY id),'')) FROM qa_plan_executions "
        "WHERE deployment_run_id=%s AND COALESCE(deployment_stage,'')=%s",
        (str(run_id), str(stage or "")),
    ).fetchone()
    return str(row[0])


def begin_inputs(
    conn: Any, run_id: str, stage: str | None, *, run_fingerprint: str | None = None
) -> str:
    """Digest the run's QA facts and its stage executions; constant statements."""
    from yoke_core.domain.deployment_run_qa_fingerprint import run_qa_fingerprint

    run = run_fingerprint or run_qa_fingerprint(conn, str(run_id))
    return f"{run}:{_executions_digest(conn, run_id, stage)}"


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
    machine: str | None,
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
        conn, roster, **scope, machine=machine, session_id=session_id
    )
    if completed is not None:
        return {**completed, "remaining_requirement_count": remaining}
    remaining = item_remaining if remaining is None else remaining
    validate_roster_machine(conn, roster, machine)
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
    "admit_member",
    "begin_inputs",
    "prepare_roster",
]
