# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any, Dict

from unittest import mock

import pytest

from yoke_core.domain import deploy_pipeline_stage_receipt as target_module

from yoke_core.domain.deploy_image_tag import canonical_image_tag

RUN_ID = "run-receipt-wrapper"

LINEAGE = "f" * 40

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
    allocate = mock.Mock(
        return_value={"receipt_id": 99, "attempt_number": 1, "status": "pending"}
    )
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
    with (
        mock.patch.object(
            target_module.control_plane, "allocate_stage_receipt", allocate
        ),
        mock.patch.object(
            target_module.control_plane, "complete_stage_receipt", complete
        ),
        mock.patch.object(
            target_module.control_plane, "latest_stage_receipt", latest_fn
        ),
        mock.patch.object(
            target_module,
            "_dispatch_step_runner",
            mock.Mock(return_value=dispatch_return, side_effect=dispatch_side_effect),
        ) as dispatch,
    ):
        result = target_module.dispatch_step_runner_with_receipt(
            stage, stages=stages, **{**_BASE_KWARGS, **overrides}
        )
    return result, allocate, complete, latest_fn, dispatch
