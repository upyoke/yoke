"""GitHub Actions REST path segments reject traversal and metacharacters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yoke_core.domain.handlers.github_actions_check_ci import CheckCiRequest
from yoke_core.domain.handlers.github_actions_run import RunGetRequest
from yoke_core.domain.handlers.github_actions_workflow import (
    RunJobsCountRequest,
    WorkflowDispatchOnceRequest,
    WorkflowDispatchRequest,
    WorkflowFindRunRequest,
)


_UNSAFE_PATH_SEGMENTS = ("/", "..", "%2f", "?", "#")


@pytest.mark.parametrize("unsafe", _UNSAFE_PATH_SEGMENTS)
@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            WorkflowDispatchRequest,
            {
                "repo": "upyoke/platform",
                "workflow": "deploy.yml",
                "project": "platform",
                "correlation_input": "yoke_dispatch_id",
            },
        ),
        (
            WorkflowDispatchOnceRequest,
            {
                "repo": "upyoke/externalwebapp",
                "workflow": "externalwebapp-deploy.yml",
                "project": "externalwebapp",
            },
        ),
        (
            WorkflowFindRunRequest,
            {
                "repo": "upyoke/platform",
                "workflow": "deploy.yml",
                "project": "platform",
                "head_sha": "abc123",
            },
        ),
        (
            CheckCiRequest,
            {
                "repo": "upyoke/platform",
                "workflow": "ci.yml",
                "project": "platform",
            },
        ),
    ],
)
def test_workflow_path_segments_reject_metacharacters(
    model,
    payload: dict[str, object],
    unsafe: str,
) -> None:
    invalid = {**payload, "workflow": unsafe}

    with pytest.raises(ValidationError, match="workflow"):
        model.model_validate(invalid)


@pytest.mark.parametrize("unsafe", _UNSAFE_PATH_SEGMENTS)
@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            RunJobsCountRequest,
            {
                "repo": "upyoke/platform",
                "run_id": "123",
                "project": "platform",
            },
        ),
        (
            RunGetRequest,
            {
                "repo": "upyoke/platform",
                "run_id": "123",
                "project": "platform",
            },
        ),
    ],
)
def test_run_path_segments_reject_metacharacters(
    model,
    payload: dict[str, object],
    unsafe: str,
) -> None:
    invalid = {**payload, "run_id": unsafe}

    with pytest.raises(ValidationError, match="run_id"):
        model.model_validate(invalid)


@pytest.mark.parametrize("workflow", ["deploy.yml", "release-v2.yaml", "731"])
def test_workflow_identifiers_accept_file_segments_and_positive_ids(
    workflow: str,
) -> None:
    parsed = WorkflowFindRunRequest(
        repo="upyoke/platform",
        workflow=workflow,
        project="platform",
        head_sha="abc123",
    )
    assert parsed.workflow == workflow


def test_run_identifier_accepts_positive_integer_text() -> None:
    parsed = RunGetRequest(
        repo="upyoke/platform",
        run_id="731",
        project="platform",
    )
    assert parsed.run_id == "731"
