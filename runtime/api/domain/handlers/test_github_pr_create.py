"""Tests for the ``github.pr.create`` handler.

REST calls are mocked at the domain-helper seam
(``github_pr_rest.create_pull_request``), the same monkeypatch pattern
the sibling github_actions handler tests use. No live network, no real
PR creation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from yoke_core.domain.handlers import github_pr_create
from yoke_core.domain.handlers.github_pr_create import handle_pr_create
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


_RESOLVED = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghs_test_token",
)


def _make_request(
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
    include_project: bool = True,
) -> FunctionCallRequest:
    if payload is None:
        payload = {"title": "cli sweep: function-call fixes", "head": "cli-sweep-fixes"}
    payload = dict(payload)
    if include_project:
        payload.setdefault("project", "yoke")
    return FunctionCallRequest(
        function="github.pr.create",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


@pytest.fixture
def _resolver_ok(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **kw: _RESOLVED,
    )


@pytest.fixture
def _rest_recorder(monkeypatch):
    calls = []

    def fake_create(repo, *, title, head, base, body=None, draft=False, token):
        calls.append({
            "repo": repo, "title": title, "head": head, "base": base,
            "body": body, "draft": draft, "token": token,
        })
        return {"number": 41, "url": "https://github.com/upyoke/yoke/pull/41"}

    monkeypatch.setattr(
        "yoke_core.domain.github_pr_rest.create_pull_request", fake_create,
    )
    return calls


class TestValidation:
    def test_rejects_missing_project(self):
        outcome = handle_pr_create(_make_request(include_project=False))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"
        assert "project" in outcome.error.message

    def test_rejects_non_global_target(self):
        outcome = handle_pr_create(_make_request(target_kind="item"))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"

    def test_rejects_missing_title(self):
        outcome = handle_pr_create(_make_request({"head": "branch-x"}))
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"
        assert "title" in outcome.error.message

    def test_rejects_missing_head(self):
        outcome = handle_pr_create(_make_request({"title": "T"}))
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"
        assert "head" in outcome.error.message

    def test_rejects_empty_base(self):
        outcome = handle_pr_create(_make_request(
            {"title": "T", "head": "b", "base": ""}
        ))
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"


class TestCreate:
    def test_creates_pr_on_capability_resolved_repo(
        self, _resolver_ok, _rest_recorder,
    ):
        outcome = handle_pr_create(_make_request())
        assert outcome.primary_success
        # repo comes from the project's GitHub capability, not the payload.
        assert _rest_recorder == [{
            "repo": "upyoke/yoke",
            "title": "cli sweep: function-call fixes",
            "head": "cli-sweep-fixes",
            "base": "main",
            "body": None,
            "draft": False,
            "token": "ghs_test_token",
        }]
        assert outcome.result_payload == {
            "number": 41,
            "url": "https://github.com/upyoke/yoke/pull/41",
        }

    def test_optional_fields_pass_through(self, _resolver_ok, _rest_recorder):
        outcome = handle_pr_create(_make_request({
            "title": "T",
            "head": "feature-x",
            "base": "stage",
            "body": "## Summary\n\nDetails.",
            "draft": True,
        }))
        assert outcome.primary_success
        call = _rest_recorder[0]
        assert call["base"] == "stage"
        assert call["body"] == "## Summary\n\nDetails."
        assert call["draft"] is True

    def test_transport_error_surfaces_as_error_envelope(
        self, monkeypatch, _resolver_ok,
    ):
        from yoke_core.domain.gh_rest_transport import RestUnprocessableError

        def _raise(*a, **kw):
            raise RestUnprocessableError(
                "HTTP 422: A pull request already exists", status=422,
            )

        monkeypatch.setattr(
            "yoke_core.domain.github_pr_rest.create_pull_request", _raise,
        )
        outcome = handle_pr_create(_make_request())
        assert not outcome.primary_success
        assert outcome.error.code == "rest_transport_error"
        assert "already exists" in outcome.error.message

    def test_missing_app_credentials_surface_as_auth_error(self, monkeypatch):
        from yoke_core.domain.project_github_auth import MissingAppCredentials

        def _raise(project, **kw):
            raise MissingAppCredentials(project, "App credentials missing")

        monkeypatch.setattr(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            _raise,
        )
        outcome = handle_pr_create(_make_request())
        assert not outcome.primary_success
        assert outcome.error.code == "project_auth_error"


class TestRegistration:
    def test_registration_entry_present(self):
        ids = {entry["function_id"] for entry in github_pr_create.REGISTRATIONS}
        assert ids == {"github.pr.create"}

    def test_registration_is_global_targeted(self):
        for entry in github_pr_create.REGISTRATIONS:
            assert entry["target_kinds"] == ["global"]
            assert entry["claim_required_kind"] is None
            assert entry["adapter_status"] == "live"
