"""The release train carries registered environment names end to end.

A hosted release flow deploys to an environment addressed everywhere by its
registered name (``prod``/``stage``): the dispatched workflows accept only
those names, and every Yoke surface they call back into — the fleet-preflight
receipt gate, the desired-pin writer — is keyed by the same name, so the
name is what the dispatch must carry.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import deploy_pipeline_github_workflow
from yoke_core.domain import deploy_pipeline_step_runners
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    resolve_workflow_inputs,
)
from yoke_core.domain.release_pin_capability import route_for_environment


ROOT = Path(__file__).resolve().parents[3]

PIN_CAPABILITY = {
    "desired_pin_path": "release.yoke_pin",
}


def test_hosted_flows_declare_the_placeholder_not_a_hardcoded_label() -> None:
    document = json.loads(
        (ROOT / ".yoke" / "deployment-flows.json").read_text(encoding="utf-8")
    )
    dispatched = [
        stage
        for flow in document["flows"]
        for stage in flow["stages"]
        if stage.get("step_runner") == "github-actions-workflow"
    ]

    assert dispatched
    assert {
        stage["inputs"]["target_environment"] for stage in dispatched
    } == {"{target_environment}"}


def test_target_environment_placeholder_resolves_to_the_registered_name() -> None:
    resolved = resolve_workflow_inputs(
        {"target_environment": "{target_environment}", "release_mode": "hotfix"},
        head_sha="a" * 40,
        run_id="run-test",
        target_environment="prod",
    )

    assert resolved == {"target_environment": "prod", "release_mode": "hotfix"}


def test_prod_flow_dispatches_the_registered_environment_name() -> None:
    gh_calls = []

    def _fake_gh(*args, **_kwargs):
        gh_calls.append(args)
        if args and args[0] == "trigger":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="new-run-id\n",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

    with mock.patch.object(
        deploy_pipeline_github_workflow, "_run_cmd",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="abc1234\n",
        ),
    ), mock.patch.object(
        deploy_pipeline_github_workflow, "_github_actions", side_effect=_fake_gh,
    ), mock.patch.object(
        deploy_pipeline_github_workflow, "_poll_github_actions",
        return_value=(0, "completed: success"),
    ), mock.patch.object(
        deploy_pipeline_github_workflow, "_emit_run_event",
    ):
        rc, diag = deploy_pipeline_step_runners._dispatch_step_runner(
            {
                "step_runner": "github-actions-workflow",
                "name": "hosted-release",
                "config": {
                    "workflow": "platform-release-bridge.yml",
                    "dispatch_correlation_input": "yoke_dispatch_id",
                    "inputs": {
                        "target_environment": "{target_environment}",
                        "release_mode": "hotfix",
                        "product_sha": "{head_sha}",
                        "deployment_run_id": "{run_id}",
                    },
                    "ref": "main",
                    "reconcile_by_head_sha": False,
                    "wait_for_ci": False,
                },
            },
            run_id="run-test",
            member_items=[],
            github_repo="owner/repo",
            project="yoke",
            project_repo_path="",
            branch="",
            first_item="",
            timeout_min=30,
            fresh=False,
            environment_name="prod",
            gate_branch="main",
            release_lineage="a" * 40,
            sd="/tmp/sd",
        )

    assert (rc, diag) == (0, "")
    trigger = next(call for call in gh_calls if call and call[0] == "trigger")
    assert "target_environment=prod" in trigger
    assert "deployment_run_id=run-test" in trigger


def test_dispatched_name_is_the_key_the_pin_writer_routes_on() -> None:
    assert route_for_environment(PIN_CAPABILITY, "prod").environment == "prod"
    assert route_for_environment(PIN_CAPABILITY, "stage").environment == "stage"

    with pytest.raises(ValueError, match="non-empty"):
        route_for_environment(PIN_CAPABILITY, "")
