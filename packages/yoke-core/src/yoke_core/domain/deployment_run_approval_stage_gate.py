"""Evaluate a run's human approval stage while holding the run lock only to write.

Everything whose cost grows with the run is read before the
``deployment_runs`` row lock: each member's own ``done`` decision, the batch,
the stage's request history, and for a brand-new request the git-derived
release contents and screenshot evidence. The lock then covers one cheap
re-check of :func:`approval_inputs_fingerprint` and the write. A change
committed between the read and the lock fails the re-check, and the whole
read runs again while the lock is held, so a stale read is never written.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from yoke_core.domain.approval_gate import (
    ApprovalGateVerdict,
    role_authorities_for,
    verdict_from_request_history,
)
from yoke_core.domain.decision_related_evidence import related_screenshot_evidence
from yoke_core.domain.decision_requests import (
    create_decision_request,
    list_subject_requests,
)
from yoke_core.domain.deployment_run_approval_inputs import (
    approval_inputs_fingerprint,
)

_WAITING = "the stage is waiting for a human decision"


@dataclass(frozen=True)
class _PreparedGate:
    run: dict[str, Any]
    stage: str
    policy: Any
    subject_context: dict[str, Any]
    history: list[dict[str, Any]]
    matches: Callable[[dict[str, Any]], bool]
    verdict: Optional[ApprovalGateVerdict]
    originator: Optional[int]


def _stage_policy(run: dict[str, Any], run_id: str, requested_stage: str):
    from yoke_core.domain.approval import parse_flow_stages, resolve_approval
    from yoke_core.domain.flow_validation import (
        MISSING_STAGE_APPROVALS,
        parse_stage_approvals,
    )

    if run["status"] != "executing" or not run["current_stage"]:
        raise ValueError(
            f"deployment run {run_id!r} is not waiting at an executing stage"
        )
    stage = str(run["current_stage"])
    if stage != requested_stage:
        raise ValueError(
            f"deployment run {run_id!r} is waiting at stage {stage!r}, not "
            f"{requested_stage!r}; re-read the run with "
            f"`yoke deployment-runs stages {run_id}` and evaluate the stage "
            "it is actually waiting at"
        )
    stages = parse_flow_stages(str(run["stages"]))
    resolution = resolve_approval(stages, stage)
    if not resolution.approved:
        raise ValueError(resolution.error or "stage does not accept approval")
    stage_def = next(entry for entry in stages if entry.name == stage)
    if "approvals" not in stage_def.config:
        raise ValueError(MISSING_STAGE_APPROVALS.format(name=stage))
    policy = parse_stage_approvals(
        stage_def.config.get("approvals"),
        path=f"stage {stage!r} approvals",
    )
    return stage, stages, policy


def _history_verdict(
    conn: Any, prepared: _PreparedGate, session_id: str
) -> Optional[ApprovalGateVerdict]:
    return verdict_from_request_history(
        conn,
        prepared.history,
        snapshot_matches=prepared.matches,
        session_id=session_id,
        stale_reason="deployment run flow or target changed",
        reraise_after_reject=False,
        waiting_reason=_WAITING,
        approved_reason="the declared approval was resolved",
        rejected_reason="the stage was rejected",
    )


def _stale_pending(prepared: _PreparedGate) -> bool:
    """Whether the history verdict would withdraw a pending request.

    That withdrawal is the history verdict's only write, so the unlocked
    read skips the verdict for such a request and leaves both the
    withdrawal and its replacement to the locked write.
    """
    latest = prepared.history[0] if prepared.history else None
    return bool(
        latest is not None
        and latest.get("status") == "pending"
        and not prepared.matches(latest)
    )


def _prepare(
    conn: Any,
    run: dict[str, Any],
    *,
    run_id: str,
    requested_stage: str,
    originator_actor_id: Optional[int],
    session_id: str,
    commit_members: bool,
) -> _PreparedGate | ApprovalGateVerdict:
    """Read everything the gate decides from; return a blocker verdict early."""
    from yoke_core.domain.deployment_approval_requests import (
        _deployment_subject_context,
        _existing_actor_id,
        _matches_deployment_snapshot,
        _release_contents,
    )
    from yoke_core.domain.deployment_run_member_approvals import (
        shared_approval_blocker,
    )

    stage, stages, policy = _stage_policy(run, run_id, requested_stage)
    if blocked := shared_approval_blocker(conn, run_id, commit=commit_members):
        return blocked
    target = str(run["target_environment"] or run["target_tier"] or "merge-only")
    subject_context = _deployment_subject_context(conn, run, stages, stage, target)
    expected = {
        field: subject_context[field]
        for field in ("run_id", "flow", "stage", "batch", "shipping")
    }
    prepared = _PreparedGate(
        run=run,
        stage=stage,
        policy=policy,
        subject_context=subject_context,
        history=list_subject_requests(conn, "deployment_stage", f"{run_id}:{stage}"),
        matches=lambda request: _matches_deployment_snapshot(request, expected),
        verdict=None,
        originator=_existing_actor_id(
            conn,
            originator_actor_id
            if originator_actor_id is not None
            else run["created_by"],
        ),
    )
    verdict = None
    if not _stale_pending(prepared):
        verdict = _history_verdict(conn, prepared, session_id)
    if verdict is None:
        # Freeze the git-derived release facts only for a new request.
        subject_context["carried"] = _release_contents(conn, run_id)
        subject_context["evidence"] = related_screenshot_evidence(
            conn,
            deployment_run_id=run_id,
            expected_revision=subject_context["shipping"]["release_lineage"],
        )
    return replace(prepared, verdict=verdict)


def _write(
    conn: Any, prepared: _PreparedGate, *, session_id: str
) -> ApprovalGateVerdict:
    """Under the run lock: withdraw a stale request, then answer or create."""
    verdict = prepared.verdict
    if verdict is None and _stale_pending(prepared):
        verdict = _history_verdict(conn, prepared, session_id)
    if verdict is not None:
        conn.commit()
        return verdict
    run = prepared.run
    request, _ = create_decision_request(
        conn,
        kind="deployment_stage_approval",
        subject_type="deployment_stage",
        subject_key=f"{run['id']}:{prepared.stage}",
        project_id=int(run["project_id"]),
        originator_actor_id=prepared.originator,
        role_authorities=role_authorities_for(
            project_id=int(run["project_id"]),
            org_id=run["org_id"],
            role_names=prepared.policy.roles,
        ),
        named_actor_ids=prepared.policy.actors,
        approval_mode=prepared.policy.mode,
        subject_context=prepared.subject_context,
        session_id=session_id,
    )
    return ApprovalGateVerdict(False, int(request["id"]), "pending", None, _WAITING)


def evaluate_stage_gate(
    conn: Any,
    *,
    run_id: str,
    requested_stage: str,
    originator_actor_id: Optional[int],
    session_id: str,
) -> ApprovalGateVerdict:
    """Read unlocked, lock the run, re-check, write, and commit to release it.

    A member blocker returns before the run lock: its own item decisions are
    written and committed by the item gate under the item's lock, and the
    run itself has nothing to write. When the re-check finds a committed
    change, the read runs again under the lock with member writes left in
    this transaction, so the one commit that releases the lock also lands
    them.
    """
    from yoke_core.domain.deployment_approval_requests import _run

    keys = dict(
        run_id=run_id,
        requested_stage=requested_stage,
        originator_actor_id=originator_actor_id,
        session_id=session_id,
    )
    before = approval_inputs_fingerprint(conn, run_id, requested_stage)
    prepared = _prepare(conn, _run(conn, run_id), commit_members=True, **keys)
    if isinstance(prepared, ApprovalGateVerdict):
        return prepared
    locked = _run(conn, run_id, for_update=True)
    if approval_inputs_fingerprint(conn, run_id, requested_stage) != before:
        prepared = _prepare(conn, locked, commit_members=False, **keys)
        if isinstance(prepared, ApprovalGateVerdict):
            conn.commit()
            return prepared
    return _write(conn, prepared, session_id=session_id)


__all__ = ["evaluate_stage_gate"]
