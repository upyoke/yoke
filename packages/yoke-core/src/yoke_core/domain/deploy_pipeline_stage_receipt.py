"""Durable stage-receipt production wrapping deployment step-runner dispatch.

A deployment flow's QA stage names an earlier ``source_stage`` whose observed
target it reads through ``deployment_stage_receipt_for_qa``
(``deployment_qa_execution_target.py``). The producing stage itself need not
declare its own ``target`` block — only the consuming QA stage does — so this
module scans the flow's own stage list for every QA stage that names the
stage about to execute, requires them to agree on one target, dispatches to
THAT target (not the run's single ``target_environment`` field, which is
merely the default for stages nobody's QA constrains), and completes the
receipt with genuinely observed evidence after.

Evidence is generic, not step-runner-specific: a receipt-producing dispatch
proves its own candidate identity by returning a non-empty diagnostic on
success (each step runner's own "provider-specific verification", e.g.
health-check's build assertion); an empty diagnostic on success means that
runner has nothing verified to report yet and this module refuses rather
than fabricate a "ready" receipt from a bare success code. A ``run_preview``
target is refused outright: nothing in this installation can yet read back
an ephemeral preview's served commit to prove it matches the pinned
candidate, so no runner may back one until that verification exists.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from yoke_core.domain import deploy_pipeline_control_plane as control_plane
from yoke_core.domain.deploy_pipeline_step_runners import _dispatch_step_runner

SUPPORTED_TARGET_KINDS = frozenset({"persistent_environment"})


def receipt_consumer_target(
    stages: List[Dict[str, Any]], stage_name: str
) -> Optional[Dict[str, Any]]:
    """Return the target every QA stage consuming ``stage_name`` agrees on.

    Raises ``ValueError`` when two consuming QA stages disagree, since that
    is a flow-configuration defect, not a runtime dispatch outcome.
    """
    agreed: Optional[Dict[str, Any]] = None
    for candidate in stages:
        if not isinstance(candidate, Mapping):
            continue
        target = candidate.get("target")
        if not isinstance(target, Mapping):
            continue
        if str(target.get("source_stage") or "") != stage_name:
            continue
        target = dict(target)
        if agreed is None:
            agreed = target
        elif agreed != target:
            raise ValueError(
                f"stage {stage_name!r} backs QA targets that disagree: "
                f"{agreed} vs {target}"
            )
    return agreed


def _next_correlation_id(run_id: str, stage_name: str) -> str:
    """Reuse a still-pending attempt's identity; mint a fresh one otherwise.

    A transport retry of the same in-flight dispatch (a crashed driver
    resumed at the same stage) must settle the receipt it already opened. An
    intentional new physical attempt — the prior one already reached a
    terminal status — must never reuse, and thereby silently authorize, a
    completed receipt; it gets a new attempt and correlation instead.
    """
    latest = control_plane.latest_stage_receipt(run_id, stage_name=stage_name)
    if latest is not None and str(latest.get("status")) == "pending":
        return str(latest["correlation_id"])
    return f"{uuid.uuid4()}:{stage_name}"


def dispatch_step_runner_with_receipt(
    stage: Dict[str, Any],
    *,
    stages: List[Dict[str, Any]],
    run_id: str,
    member_items: List[str],
    github_repo: str,
    project: str,
    project_repo_path: str,
    branch: str,
    first_item: str,
    first_item_label: str = "",
    timeout_min: int,
    fresh: bool,
    image_tag: str = "",
    environment_name: str = "",
    gate_branch: str,
    release_lineage: str,
    product_repo_path: str = "",
    sd: Optional[str] = None,
) -> tuple[int, str]:
    """Dispatch a stage, recording a durable receipt when a later QA stage
    consumes it as its ``source_stage``. Every other stage dispatches
    unchanged.
    """
    stage_name = str(stage.get("name") or "")
    step_runner = str(stage.get("step_runner") or "")

    def _dispatch(*, dispatch_environment: str) -> tuple[int, str]:
        return _dispatch_step_runner(
            stage,
            run_id=run_id,
            member_items=member_items,
            github_repo=github_repo,
            project=project,
            project_repo_path=project_repo_path,
            branch=branch,
            first_item=first_item,
            first_item_label=first_item_label,
            timeout_min=timeout_min,
            fresh=fresh,
            image_tag=image_tag,
            environment_name=dispatch_environment,
            gate_branch=gate_branch,
            release_lineage=release_lineage,
            product_repo_path=product_repo_path,
            sd=sd,
        )

    try:
        target = receipt_consumer_target(stages, stage_name)
    except ValueError as exc:
        return 1, str(exc)
    if target is None:
        return _dispatch(dispatch_environment=environment_name)

    target_kind = str(target.get("kind") or "")
    if target_kind not in SUPPORTED_TARGET_KINDS:
        return 1, (
            f"stage {stage_name!r} backs a {target_kind!r} QA target, which "
            "this installation cannot yet produce a verified receipt for "
            "(no producer proves the deployed candidate's exact commit for "
            "that target kind); this requires an integration this rollout "
            "does not include yet"
        )

    # Dispatch to the target the flow itself declares, not the run's single
    # `target_environment` default — that default only applies to stages no
    # QA stage constrains.
    dispatch_environment = str(target.get("environment") or "") or environment_name

    correlation_id = _next_correlation_id(run_id, stage_name)
    receipt = control_plane.allocate_stage_receipt(
        run_id,
        stage_name=stage_name,
        correlation_id=correlation_id,
        target_kind=target_kind,
        executor=step_runner,
    )

    try:
        exec_rc, exec_diag = _dispatch(dispatch_environment=dispatch_environment)
    except Exception as exc:
        control_plane.complete_stage_receipt(
            run_id,
            receipt_id=receipt["receipt_id"],
            correlation_id=correlation_id,
            status="failed",
            failure_reason=f"dispatch raised: {exc}",
        )
        raise

    if exec_rc == -2:
        # Awaiting human approval: nothing observed yet. Leave the receipt
        # pending; the resumed dispatch reuses and completes it.
        return exec_rc, exec_diag

    if exec_rc in (0, -3) and exec_diag:
        # Generic evidence contract: a receipt-producing stage proves its
        # candidate identity by populating its own diagnostic on success.
        control_plane.complete_stage_receipt(
            run_id,
            receipt_id=receipt["receipt_id"],
            correlation_id=correlation_id,
            status="ready",
            target_name=dispatch_environment or None,
            observed_release_lineage=release_lineage,
            observed_artifact_identity=exec_diag,
            executor_receipt=exec_diag,
        )
        return exec_rc, exec_diag

    if exec_rc in (0, -3):
        failure_reason = (
            f"stage {stage_name!r} step runner {step_runner!r} exited "
            f"{exec_rc} with no verifiable candidate evidence; that runner "
            "has no provider-specific verification wired yet and cannot "
            "back a QA receipt"
        )
    else:
        failure_reason = exec_diag or f"stage {stage_name!r} exited {exec_rc}"
    control_plane.complete_stage_receipt(
        run_id,
        receipt_id=receipt["receipt_id"],
        correlation_id=correlation_id,
        status="failed",
        failure_reason=failure_reason,
    )
    return (1 if exec_rc in (0, -3) else exec_rc), failure_reason


__all__ = ["dispatch_step_runner_with_receipt", "receipt_consumer_target"]
