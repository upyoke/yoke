"""Persisted stage JSON keeps its scoped target all the way to dispatch.

These exercise the real path a release takes: the stage list a
``deployment_flows`` row stores, through the pipeline's own normalization,
into receipt-producing dispatch. Unit fixtures that hand an
already-normalized stage straight to a step runner cannot see the field a
stage loses on the way there, which is how a scoped QA target went missing
between the flow that declared it and the receipt that was supposed to
prove it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest import mock

from yoke_core.domain import browser_qa_preview_identity
from yoke_core.domain import deploy_ephemeral
from yoke_core.domain import deploy_pipeline_stage_receipt as stage_receipt
from yoke_core.domain import deploy_pipeline_step_runners as step_runners
from yoke_core.domain import served_revision_probe
from yoke_core.domain.browser_qa_preview_identity import PreviewIdentityTarget
from yoke_core.domain.deploy_image_tag import canonical_image_tag
from yoke_core.domain.deploy_pipeline_reporting import _parse_stages
from yoke_core.domain.deploy_preview_dispatch_boundary import (
    release_preview_identity,
)
from yoke_core.domain.ephemeral_substrate import (
    TRIGGER_GITHUB_PUSH,
    preview_url,
)
from yoke_core.domain.served_revision_probe import ProbeOutcome


RUN_ID = "run-20260101-001"
PROJECT = "yoke"
LINEAGE = "a1b2c3d4" * 5
VERIFIED_BUILD = canonical_image_tag(LINEAGE)
IDENTITY_PATH = "/candidate-revision"
PREVIEW_DOMAIN = "preview.example.test"

_DISPATCH_KWARGS: Dict[str, Any] = dict(
    run_id=RUN_ID,
    member_items=["1"],
    github_repo="owner/repo",
    project=PROJECT,
    project_repo_path="/tmp/repo",
    branch="feature",
    first_item="1",
    first_item_label="ITEM-1",
    timeout_min=5,
    fresh=False,
    image_tag="",
    environment_name="prod",
    gate_branch="main",
    release_lineage=LINEAGE,
)


def _preview_policy():
    """This project publishes previews from its own deploy workflow."""
    return mock.patch.object(
        browser_qa_preview_identity,
        "resolve_preview_policy",
        mock.Mock(
            return_value=PreviewIdentityTarget(
                path=IDENTITY_PATH,
                trigger=TRIGGER_GITHUB_PUSH,
                preview_domain=PREVIEW_DOMAIN,
            )
        ),
    )


def _probe(outcome: ProbeOutcome):
    return mock.patch.object(
        served_revision_probe,
        "probe_served_revision",
        mock.Mock(return_value=outcome),
    )


def _persisted(*stages: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize a stage list exactly as an executing run does."""
    return _parse_stages(json.dumps(list(stages)))


def _deploy_stage() -> Dict[str, Any]:
    return {
        "name": "deploy",
        "step_runner": "health-check",
        "stage_kind": "execution",
        "target": {"kind": "persistent_environment", "environment": "stage"},
    }


def _preview_stage() -> Dict[str, Any]:
    return {
        "name": "release-preview",
        "step_runner": "github-actions-workflow",
        "stage_kind": "execution",
        "workflow": "deploy-preview.yml",
        "dispatch_correlation_input": "yoke_dispatch_id",
        "inputs": {"revision": "{head_sha}", "preview_slug": "{preview_slug}"},
        "target": {"kind": "run_preview", "capability": "ephemeral-env"},
    }


def _qa_stage(source_stage: str, target: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": f"{source_stage}-qa",
        "step_runner": "qa",
        "stage_kind": "qa",
        "scope": "run",
        "target": {**target, "source_stage": source_stage},
        "verdict": {"mode": "agent_only"},
    }


def _dispatch_persisted(
    stages: List[Dict[str, Any]],
    *,
    index: int = 0,
    dispatch_return: tuple[int, str] = (0, VERIFIED_BUILD),
    latest_receipt: Dict[str, Any] | None = None,
    **overrides: Any,
):
    allocate = mock.Mock(
        return_value={"receipt_id": 7, "attempt_number": 1, "status": "pending"}
    )
    complete = mock.Mock(return_value={"receipt_id": 7, "status": "ready"})
    latest = mock.Mock(return_value=latest_receipt)
    inner = mock.Mock(return_value=dispatch_return)
    with (
        mock.patch.object(
            stage_receipt.control_plane, "allocate_stage_receipt", allocate
        ),
        mock.patch.object(
            stage_receipt.control_plane, "complete_stage_receipt", complete
        ),
        mock.patch.object(stage_receipt.control_plane, "latest_stage_receipt", latest),
        mock.patch.object(stage_receipt, "_dispatch_step_runner", inner),
    ):
        result = stage_receipt.dispatch_step_runner_with_receipt(
            stages[index],
            stages=stages,
            **{**_DISPATCH_KWARGS, **overrides},
        )
    return result, allocate, complete, inner


class TestNormalizationPreservesTheStageContract:
    def test_persisted_stage_keeps_the_fields_execution_reads(self) -> None:
        stages = _persisted(
            _deploy_stage(),
            _qa_stage(
                "deploy", {"kind": "persistent_environment", "environment": "stage"}
            ),
        )

        assert stages[0]["target"] == {
            "kind": "persistent_environment",
            "environment": "stage",
        }
        assert stages[0]["stage_kind"] == "execution"
        assert stages[1]["scope"] == "run"
        assert stages[1]["target"]["source_stage"] == "deploy"

    def test_name_and_step_runner_are_normalized_to_strings(self) -> None:
        stages = _persisted({"name": "deploy", "step_runner": None})

        assert stages[0]["name"] == "deploy"
        assert stages[0]["step_runner"] == ""

    def test_runner_fields_stay_readable_through_config(self) -> None:
        stages = _persisted(_preview_stage())

        assert stages[0]["config"]["workflow"] == "deploy-preview.yml"
        assert stages[0]["config"]["inputs"] == {
            "revision": "{head_sha}",
            "preview_slug": "{preview_slug}",
        }


class TestScopedTargetReachesReceiptProduction:
    def test_persistent_target_dispatches_to_the_environment_the_flow_names(
        self,
    ) -> None:
        stages = _persisted(
            _deploy_stage(),
            _qa_stage(
                "deploy", {"kind": "persistent_environment", "environment": "stage"}
            ),
        )

        result, allocate, complete, inner = _dispatch_persisted(stages)

        assert result == (0, VERIFIED_BUILD)
        # The run defaults to prod; the flow's own QA target names stage.
        assert inner.call_args.kwargs["environment_name"] == "stage"
        assert allocate.call_args.kwargs["target_kind"] == "persistent_environment"
        assert complete.call_args.kwargs["status"] == "ready"

    def test_run_preview_target_proves_the_frozen_candidate(self) -> None:
        stages = _persisted(
            _preview_stage(),
            _qa_stage("release-preview", {"kind": "run_preview"}),
        )
        expected_origin = preview_url(
            release_preview_identity(_preview_stage(), run_id=RUN_ID),
            PREVIEW_DOMAIN,
        )

        with (
            _preview_policy(),
            _probe(
                ProbeOutcome(f"{expected_origin}{IDENTITY_PATH}", served=LINEAGE)
            ) as probe,
        ):
            result, allocate, complete, inner = _dispatch_persisted(
                stages, dispatch_return=(-3, "preview deployed")
            )

        rc, diag = result
        assert rc == -3
        assert LINEAGE in diag
        inner.assert_called_once()
        assert allocate.call_args.kwargs["target_kind"] == "run_preview"
        # Proof is about this run's own preview, at the origin its identity
        # names, for the exact candidate the run froze.
        assert probe.call_args.args[0] == expected_origin
        assert probe.call_args.kwargs["expected_sha"] == LINEAGE
        assert complete.call_args.kwargs["status"] == "ready"
        assert complete.call_args.kwargs["target_name"] == RUN_ID
        assert complete.call_args.kwargs["observed_release_lineage"] == LINEAGE

    def test_run_preview_stage_that_cannot_carry_the_candidate_refuses(self) -> None:
        stage = _preview_stage()
        stage.pop("inputs")
        stages = _persisted(
            stage, _qa_stage("release-preview", {"kind": "run_preview"})
        )

        with _preview_policy(), _probe(ProbeOutcome("", served=LINEAGE)) as probe:
            result, _allocate, complete, inner = _dispatch_persisted(
                stages, dispatch_return=(-3, "preview deployed")
            )

        rc, diag = result
        assert rc == 1
        assert "frozen candidate" in diag
        inner.assert_not_called()
        probe.assert_not_called()
        assert complete.call_args.kwargs["status"] == "failed"

    def test_stage_with_no_consuming_qa_produces_no_receipt(self) -> None:
        stages = _persisted(
            {
                "name": "deploy",
                "step_runner": "github-actions-workflow",
                "workflow": "deploy.yml",
            }
        )

        result, allocate, complete, inner = _dispatch_persisted(stages)

        assert result == (0, VERIFIED_BUILD)
        inner.assert_called_once()
        allocate.assert_not_called()
        complete.assert_not_called()

    def test_awaiting_approval_leaves_the_receipt_pending(self) -> None:
        stages = _persisted(
            _deploy_stage(),
            _qa_stage(
                "deploy", {"kind": "persistent_environment", "environment": "stage"}
            ),
        )

        result, allocate, complete, _inner = _dispatch_persisted(
            stages, dispatch_return=(-2, "awaiting approval")
        )

        assert result == (-2, "awaiting approval")
        allocate.assert_called_once()
        complete.assert_not_called()

    def test_resumed_stage_settles_the_receipt_it_already_opened(self) -> None:
        stages = _persisted(
            _deploy_stage(),
            _qa_stage(
                "deploy", {"kind": "persistent_environment", "environment": "stage"}
            ),
        )
        pending = {"status": "pending", "correlation_id": "held:deploy"}

        _result, allocate, complete, _inner = _dispatch_persisted(
            stages, latest_receipt=pending
        )

        assert allocate.call_args.kwargs["correlation_id"] == "held:deploy"
        assert complete.call_args.kwargs["correlation_id"] == "held:deploy"


class TestPreviewDeployCarriesTheFrozenCandidate:
    def test_release_preview_deploys_the_run_candidate_under_its_identity(
        self,
    ) -> None:
        stages = _persisted(
            {
                "name": "release-preview",
                "step_runner": "ephemeral-deploy",
                "stage_kind": "execution",
                "target": {"kind": "run_preview", "capability": "ephemeral-env"},
            }
        )
        deploy = mock.Mock(return_value=0)

        with mock.patch.object(deploy_ephemeral, "exec_ephemeral_deploy", deploy):
            rc, _diag = step_runners._dispatch_step_runner(
                stages[0], **_DISPATCH_KWARGS
            )

        assert rc == 0
        assert deploy.call_args.kwargs["revision"] == LINEAGE
        assert deploy.call_args.kwargs["preview_key"] == release_preview_identity(
            stages[0], run_id=RUN_ID
        )

    def test_branch_preview_still_deploys_the_branch_head(self) -> None:
        stages = _persisted(
            {"name": "branch-preview", "step_runner": "ephemeral-deploy"}
        )
        deploy = mock.Mock(return_value=0)

        with mock.patch.object(deploy_ephemeral, "exec_ephemeral_deploy", deploy):
            rc, _diag = step_runners._dispatch_step_runner(
                stages[0], **_DISPATCH_KWARGS
            )

        assert rc == 0
        assert deploy.call_args.kwargs["revision"] == ""
        assert deploy.call_args.kwargs["preview_key"] == ""
