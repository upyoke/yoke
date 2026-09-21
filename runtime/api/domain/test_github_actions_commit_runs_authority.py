"""Watching CI works where GitHub App keys are, not where the watcher is.

An HTTPS-only project machine holds no App credentials, and asking it for
them refused every watch it started while the project's registered trigger
and poll worked fine. The run listing is a control-plane read; only resolving
the ref belongs on the caller's machine.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import github_actions_commit_runs_read as read_module
from yoke_core.domain.handlers import github_actions_commit_runs as handler_module

HEAD = "a" * 40


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["yoke"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _envelope(runs: list[dict[str, Any]]) -> str:
    return json.dumps({"result": {"repo": "owner/name", "head_sha": HEAD, "runs": runs}})


def test_the_listing_is_asked_of_the_project_actions_authority(
    monkeypatch: pytest.MonkeyPatch,
):
    """No local App credential is resolved; the authority answers."""
    calls: dict = {}

    def fake_actions(*args: str, project: str, **kwargs):
        calls["args"] = list(args)
        calls["project"] = project
        return _completed(
            0,
            stdout=_envelope(
                [{"id": "7", "name": "yoke-ci", "status": "queued", "head_sha": HEAD}]
            ),
        )

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions", fake_actions
    )

    runs = read_module.matching_runs("yoke", HEAD, "yoke-ci")

    assert [run["id"] for run in runs] == ["7"]
    assert calls["project"] == "yoke"
    assert calls["args"][:2] == ["commit-runs", HEAD]
    assert "--workflow" in calls["args"]


def test_a_refused_authority_is_named_rather_than_read_as_no_runs(
    monkeypatch: pytest.MonkeyPatch,
):
    """"No runs" and "nobody could look" must not be the same answer."""
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *args, project, **kwargs: _completed(
            4, stderr="Error: no GitHub Actions authority selected\n"
        ),
    )

    with pytest.raises(read_module.CommitRunAuthorityError) as raised:
        read_module.matching_runs("yoke", HEAD, "")

    assert "no GitHub Actions authority selected" in str(raised.value)


def test_unreadable_authority_output_is_named_too(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *args, project, **kwargs: _completed(0, stdout="{"),
    )

    with pytest.raises(read_module.CommitRunAuthorityError):
        read_module.matching_runs("yoke", HEAD, "")


class _Resolved:
    repo = "owner/name"
    token = "installation-token"


def test_the_handler_selects_by_exact_sha_and_workflow_name(
    monkeypatch: pytest.MonkeyPatch,
):
    """The matching rules live with the authority, not at the call site."""
    monkeypatch.setattr(
        handler_module,
        "_validate_and_resolve_auth",
        lambda request, model, function_id, *, required_permissions: (
            model.model_validate(request.payload or {}),
            _Resolved(),
            None,
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_get",
        lambda path, *, query, token: {
            "workflow_runs": [
                {"id": 1, "name": "yoke-ci", "head_sha": HEAD, "status": "queued"},
                {"id": 2, "name": "release", "head_sha": HEAD, "status": "queued"},
                {"id": 3, "name": "yoke-ci", "head_sha": "b" * 40, "status": "queued"},
            ]
        },
    )

    outcome = handler_module.handle_commit_runs_list(
        _request(
            function=handler_module.FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={"project": "yoke", "head_sha": HEAD, "workflow": "yoke-ci"},
        )
    )

    assert outcome.primary_success
    assert [run["id"] for run in outcome.result_payload["runs"]] == ["1"]
    assert outcome.result_payload["repo"] == "owner/name"
    assert outcome.result_payload["runs"][0]["head_branch"] == ""
    assert outcome.result_payload["runs"][0]["event"] == ""


def test_the_handler_defaults_to_the_projects_bound_repository(
    monkeypatch: pytest.MonkeyPatch,
):
    """A caller with no local authority cannot name the repo either."""
    seen: dict = {}

    monkeypatch.setattr(
        handler_module,
        "_validate_and_resolve_auth",
        lambda request, model, function_id, *, required_permissions: (
            model.model_validate(request.payload or {}),
            _Resolved(),
            None,
        ),
    )

    def fake_get(path, *, query, token):
        seen["path"] = path
        seen["query"] = query
        return {"workflow_runs": []}

    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_get", fake_get)

    outcome = handler_module.handle_commit_runs_list(
        _request(
            function=handler_module.FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={"project": "yoke", "head_sha": HEAD},
        )
    )

    assert outcome.primary_success
    assert seen["path"] == "/repos/owner/name/actions/runs"
    assert seen["query"]["head_sha"] == HEAD


def test_the_handler_keeps_head_branch_and_event(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        handler_module,
        "_validate_and_resolve_auth",
        lambda request, model, function_id, *, required_permissions: (
            model.model_validate(request.payload or {}),
            _Resolved(),
            None,
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_get",
        lambda path, *, query, token: {
            "workflow_runs": [
                {
                    "id": 9,
                    "name": "yoke-ci",
                    "head_sha": HEAD,
                    "status": "completed",
                    "conclusion": "success",
                    "head_branch": "gh-readonly-queue/main/pr-1425",
                    "event": "merge_group",
                },
            ]
        },
    )

    outcome = handler_module.handle_commit_runs_list(
        _request(
            function=handler_module.FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={"project": "yoke", "head_sha": HEAD},
        )
    )

    assert outcome.primary_success
    run = outcome.result_payload["runs"][0]
    assert run["head_branch"] == "gh-readonly-queue/main/pr-1425"
    assert run["event"] == "merge_group"


def test_the_read_is_reachable_under_attended_local_authority():
    """A source-dev machine keeps the same call through local authority."""
    from yoke_core.domain.github_actions_local_authority import _ALLOWED_FUNCTIONS

    assert handler_module.FUNCTION_ID in _ALLOWED_FUNCTIONS
