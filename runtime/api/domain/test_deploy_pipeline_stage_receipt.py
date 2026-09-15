"""Stage-receipt production wraps dispatch honestly or refuses closed."""

from __future__ import annotations

from typing import Any, Dict
from unittest import mock

import pytest

from yoke_core.domain import deploy_pipeline_stage_receipt as target_module
from yoke_core.domain.deploy_image_tag import canonical_image_tag


RUN_ID = "run-receipt-wrapper"
LINEAGE = "f" * 40

#: What health-check reports having asserted the served build against when
#: the run pins this candidate — the only diagnostic that identifies it.
VERIFIED_BUILD = canonical_image_tag(LINEAGE)

_BASE_KWARGS: Dict[str, Any] = dict(
    run_id=RUN_ID,
    member_items=["1"],
    github_repo="owner/repo",
    project="yoke",
    project_repo_path="/tmp/repo",
    branch="feature",
    first_item="1",
    first_item_label="YOK-1",
    timeout_min=5,
    fresh=False,
    image_tag="",
    environment_name="stage",
    gate_branch="main",
    release_lineage=LINEAGE,
)


def _stage(name: str, step_runner: str) -> Dict[str, Any]:
    return {"name": name, "step_runner": step_runner, "stage_kind": "execution"}


def _qa_stage(
    source_stage: str,
    *,
    name: str = "release-qa",
    kind: str = "persistent_environment",
    environment: str = "stage",
) -> Dict[str, Any]:
    target: Dict[str, Any] = {"kind": kind, "source_stage": source_stage}
    if kind == "persistent_environment":
        target["environment"] = environment
    return {
        "name": name,
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "run",
        "target": target,
        "verdict": {"mode": "agent_only"},
    }


def _control_plane_mocks(*, latest: Dict[str, Any] | None = None):
    allocate = mock.Mock(return_value={"receipt_id": 99, "attempt_number": 1, "status": "pending"})
    complete = mock.Mock(return_value={"receipt_id": 99, "status": "ready"})
    latest_fn = mock.Mock(return_value=latest)
    return allocate, complete, latest_fn


def _dispatch_with(
    stage,
    stages,
    *,
    dispatch_return=None,
    dispatch_side_effect=None,
    latest=None,
    **overrides,
):
    allocate, complete, latest_fn = _control_plane_mocks(latest=latest)
    with mock.patch.object(target_module.control_plane, "allocate_stage_receipt", allocate), \
         mock.patch.object(target_module.control_plane, "complete_stage_receipt", complete), \
         mock.patch.object(target_module.control_plane, "latest_stage_receipt", latest_fn), \
         mock.patch.object(
             target_module,
             "_dispatch_step_runner",
             mock.Mock(return_value=dispatch_return, side_effect=dispatch_side_effect),
         ) as dispatch:
        result = target_module.dispatch_step_runner_with_receipt(
            stage, stages=stages, **{**_BASE_KWARGS, **overrides}
        )
    return result, allocate, complete, latest_fn, dispatch


def test_stage_with_no_consuming_qa_dispatches_unchanged() -> None:
    stage = _stage("deploy-stage", "health-check")
    stages = [stage]
    result, allocate, complete, _latest, dispatch = _dispatch_with(
        stage, stages, dispatch_return=(0, VERIFIED_BUILD)
    )
    assert result == (0, VERIFIED_BUILD)
    dispatch.assert_called_once()
    allocate.assert_not_called()
    complete.assert_not_called()


def test_run_preview_target_refuses_before_dispatch_for_any_runner() -> None:
    stage = _stage("preview-stage", "ephemeral-verify")
    stages = [stage, _qa_stage("preview-stage", kind="run_preview")]
    result, allocate, complete, _latest, dispatch = _dispatch_with(
        stage, stages, dispatch_return=(-3, "https://preview.example.test")
    )
    rc, diag = result
    assert rc == 1
    assert "cannot yet produce a verified receipt" in diag
    dispatch.assert_not_called()
    allocate.assert_not_called()
    complete.assert_not_called()


def test_disagreeing_qa_consumers_refuse_before_dispatch() -> None:
    stage = _stage("deploy-stage", "health-check")
    stages = [
        stage,
        _qa_stage("deploy-stage", name="stage-qa", environment="stage"),
        _qa_stage("deploy-stage", name="prod-qa", environment="prod"),
    ]
    result, allocate, complete, _latest, dispatch = _dispatch_with(stage, stages)
    rc, diag = result
    assert rc == 1
    assert "disagree" in diag
    dispatch.assert_not_called()
    allocate.assert_not_called()
    complete.assert_not_called()


def test_dispatch_targets_the_flows_own_declared_environment() -> None:
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage", environment="prod")]
    _result, allocate, complete, _latest, dispatch = _dispatch_with(
        stage, stages, dispatch_return=(0, VERIFIED_BUILD)
    )
    # The run's own environment_name is "stage" (see _BASE_KWARGS); the flow
    # declares "prod" for this stage's QA consumer, and dispatch follows it.
    assert dispatch.call_args.kwargs["environment_name"] == "prod"
    assert allocate.call_args.kwargs["target_kind"] == "persistent_environment"
    assert complete.call_args.kwargs["target_name"] == "prod"


def test_health_check_ready_reports_its_diagnostic_as_the_executor_receipt() -> None:
    """The diagnostic is what the runner said, not an observed identity.

    Recording it as ``observed_artifact_identity`` would make the receipt
    store refuse every run that pins one, because the store compares
    observed against pinned.
    """
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage")]
    result, allocate, complete, _latest, _dispatch = _dispatch_with(
        stage, stages, dispatch_return=(0, VERIFIED_BUILD)
    )
    assert result == (0, VERIFIED_BUILD)
    allocate.assert_called_once()
    complete.assert_called_once()
    kwargs = complete.call_args.kwargs
    assert kwargs["status"] == "ready"
    assert kwargs["executor_receipt"] == VERIFIED_BUILD
    assert kwargs["observed_artifact_identity"] is None
    assert kwargs["observed_release_lineage"] == LINEAGE


def test_verified_build_that_is_not_the_candidate_is_not_an_observation() -> None:
    """A build assertion that names another tag did not observe this one."""
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage")]
    result, _allocate, complete, _latest, _dispatch = _dispatch_with(
        stage, stages, dispatch_return=(0, "build-42")
    )
    rc, diag = result
    assert rc == 1
    assert "does not identify this run's pinned candidate" in diag
    assert complete.call_args.kwargs["status"] == "failed"


def test_run_without_a_pinned_candidate_cannot_observe_one() -> None:
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage")]
    result, _allocate, complete, _latest, _dispatch = _dispatch_with(
        stage, stages, dispatch_return=(0, VERIFIED_BUILD), release_lineage=""
    )
    rc, diag = result
    assert rc == 1
    assert "pins no candidate revision" in diag
    assert complete.call_args.kwargs["status"] == "failed"


def test_run_pinning_an_unobservable_artifact_refuses_before_dispatch() -> None:
    """No producer reads the served artifact back, so nothing could prove it."""
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage")]
    result, allocate, complete, _latest, dispatch = _dispatch_with(
        stage,
        stages,
        dispatch_return=(0, VERIFIED_BUILD),
        run_artifact_identity="registry/yoke@sha256:cafe",
    )
    rc, diag = result
    assert rc == 1
    assert "pins artifact identity" in diag
    assert "registry/yoke@sha256:cafe" in diag
    dispatch.assert_not_called()
    allocate.assert_not_called()
    complete.assert_not_called()


def test_registered_producer_reads_its_target_and_reports_a_url(monkeypatch) -> None:
    """The extension point a kind-specific producer is written against.

    A producer that reads a served URL and commit back must get the QA
    target's own selector, the dispatch identity to rejoin, and the
    project whose policy resolves the target — not a diagnostic string to
    parse.
    """
    seen: Dict[str, Any] = {}

    def _url_producer(context):
        seen["target"] = dict(context.target)
        seen["project"] = context.project
        seen["run_id"] = context.run_id
        seen["stage_name"] = context.stage_name
        seen["correlation_id"] = context.correlation_id
        seen["stage_name_from_stage"] = context.stage.get("name")
        rc, diag = context.dispatch(dispatch_environment=context.dispatch_environment)
        return (
            rc,
            diag,
            target_module.StageObservation(
                target_name="preview-42",
                observed_release_lineage="e" * 40,
                observed_url="https://preview-42.example.test/",
            ),
        )

    monkeypatch.setitem(target_module.RECEIPT_PRODUCERS, "run_preview", _url_producer)
    stage = _stage("deploy-stage", "ephemeral-verify")
    stages = [stage, _qa_stage("deploy-stage", kind="run_preview")]
    result, allocate, complete, _latest, _dispatch = _dispatch_with(
        stage, stages, dispatch_return=(0, "preview served")
    )

    assert result == (0, "preview served")
    assert seen["target"]["kind"] == "run_preview"
    assert seen["target"]["source_stage"] == "deploy-stage"
    assert seen["project"] == "yoke"
    assert seen["run_id"] == RUN_ID
    assert seen["stage_name"] == "deploy-stage"
    assert seen["stage_name_from_stage"] == "deploy-stage"
    assert seen["correlation_id"] == allocate.call_args.kwargs["correlation_id"]
    kwargs = complete.call_args.kwargs
    assert kwargs["status"] == "ready"
    assert kwargs["target_name"] == "preview-42"
    assert kwargs["observed_url"] == "https://preview-42.example.test/"
    assert kwargs["observed_release_lineage"] == "e" * 40
    assert kwargs["executor_receipt"] == "preview served"


def test_supported_target_kinds_is_the_producer_registry() -> None:
    """One list, so registering a producer cannot leave a constant behind."""
    assert target_module.SUPPORTED_TARGET_KINDS == frozenset(
        target_module.RECEIPT_PRODUCERS
    )
    assert target_module.ARTIFACT_OBSERVING_TARGET_KINDS <= (
        target_module.SUPPORTED_TARGET_KINDS
    )


def test_a_runner_that_proves_no_identity_is_refused_before_it_deploys() -> None:
    """Refused before dispatch, not after a receipt it could never settle.

    A persistent-environment producer takes its candidate identity from
    the producing runner, so a runner that returns no verified identity
    cannot back that target however it exits. Finding that out after the
    dispatch would mean a real environment changed by a run that can
    never complete.
    """
    stage = _stage("deploy-stage", "core-container-deploy")
    stages = [stage, _qa_stage("deploy-stage")]
    result, allocate, complete, _latest, dispatch = _dispatch_with(
        stage, stages, dispatch_return=(0, "")
    )
    rc, diag = result
    assert rc == 1
    assert "returns no verified candidate identity" in diag
    dispatch.assert_not_called()
    allocate.assert_not_called()
    complete.assert_not_called()


def test_human_approval_wait_leaves_receipt_pending() -> None:
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage")]
    result, allocate, complete, _latest, _dispatch = _dispatch_with(
        stage, stages, dispatch_return=(-2, "awaiting human approval")
    )
    assert result == (-2, "awaiting human approval")
    allocate.assert_called_once()
    complete.assert_not_called()


def test_correlation_reuses_a_still_pending_attempt() -> None:
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage")]
    _result, allocate, _complete, _latest, _dispatch = _dispatch_with(
        stage,
        stages,
        dispatch_return=(0, "build-1"),
        latest={"status": "pending", "correlation_id": "in-flight-correlation"},
    )
    assert allocate.call_args.kwargs["correlation_id"] == "in-flight-correlation"


def test_correlation_is_fresh_after_a_terminal_attempt() -> None:
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage")]
    _result, allocate, _complete, _latest, _dispatch = _dispatch_with(
        stage,
        stages,
        dispatch_return=(0, "build-1"),
        latest={"status": "failed", "correlation_id": "old-terminal-correlation"},
    )
    assert allocate.call_args.kwargs["correlation_id"] != "old-terminal-correlation"


def test_dispatch_exception_settles_the_receipt_failed_and_reraises() -> None:
    stage = _stage("deploy-stage", "health-check")
    stages = [stage, _qa_stage("deploy-stage")]
    allocate, complete, latest_fn = _control_plane_mocks()
    with mock.patch.object(target_module.control_plane, "allocate_stage_receipt", allocate), \
         mock.patch.object(target_module.control_plane, "complete_stage_receipt", complete), \
         mock.patch.object(target_module.control_plane, "latest_stage_receipt", latest_fn), \
         mock.patch.object(
             target_module,
             "_dispatch_step_runner",
             mock.Mock(side_effect=RuntimeError("executor blew up")),
         ):
        with pytest.raises(RuntimeError, match="executor blew up"):
            target_module.dispatch_step_runner_with_receipt(
                stage, stages=stages, **_BASE_KWARGS
            )
    assert complete.call_args.kwargs["status"] == "failed"
    assert "executor blew up" in complete.call_args.kwargs["failure_reason"]
