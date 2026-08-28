"""A 404 on the workflow-runs path is a missing workflow, not transport."""

from __future__ import annotations

import pytest

from yoke_core.domain import github_actions_rest
from yoke_core.domain.gh_rest_transport import RestNotFoundError


def test_latest_workflow_run_treats_404_as_missing_workflow(monkeypatch):
    monkeypatch.setattr(github_actions_rest, "rest_get", lambda *a, **kw: None)

    with pytest.raises(RestNotFoundError, match="missing.yml") as failure:
        github_actions_rest.latest_workflow_run(
            "upyoke/platform",
            "missing.yml",
            branch="main",
            token="ghs_x",
        )

    assert failure.value.status == 404
    assert "upyoke/platform" in str(failure.value)
    assert "transport" not in str(failure.value).lower()
    assert "authorization" not in str(failure.value).lower()


def test_latest_workflow_run_empty_runs_still_means_workflow_exists(monkeypatch):
    monkeypatch.setattr(
        github_actions_rest,
        "rest_get",
        lambda *a, **kw: {"workflow_runs": []},
    )

    assert (
        github_actions_rest.latest_workflow_run(
            "o/r",
            "ci.yml",
            branch="main",
            token="ghs_x",
        )
        is None
    )
