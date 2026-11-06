# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_health_check, deploy_pipeline_step_runners

from yoke_core.domain.deploy_cli_manifest_gate import CliManifestGateResult


def _dispatch(stage, **overrides):
    kwargs = dict(
        run_id="run-1",
        member_items=["1"],
        github_repo="o/r",
        project="yoke",
        project_repo_path="/repo",
        branch="b",
        first_item="1",
        first_item_label="YOK-1",
        timeout_min=1,
        fresh=False,
        image_tag="",
        environment_name="prod",
        gate_branch="main",
        release_lineage="",
        product_repo_path="",
        sd=None,
    )
    kwargs.update(overrides)
    return deploy_pipeline_step_runners._dispatch_step_runner(stage, **kwargs)


def _stage(step_runner, **config):
    config = {"name": "s", "step_runner": step_runner, **config}
    return {"name": "s", "step_runner": step_runner, "config": config}
