"""Tests for the ``github_actions.variable.get`` handler.

REST calls are mocked at the domain-helper seam (the same monkeypatch
pattern the set-handler tests use). Covers the exists/absent split,
auth and transport failures, and the registered-dispatch path.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from yoke_core.domain import github_variables_rest
from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    RestResponse,
    RestTransportError,
)
from yoke_core.domain.handlers import github_actions_get, github_actions_set
from yoke_core.domain.handlers.github_actions_get import handle_variable_get
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
    env={"PATH": "/usr/bin", "GH_TOKEN": "ghs_test_token"},
)


def _make_request(
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
) -> FunctionCallRequest:
    if payload is None:
        payload = {"repo": "upyoke/yoke", "name": "YOKE_PULUMI_CI_ENABLED"}
    return FunctionCallRequest(
        function="github_actions.variable.get",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


@pytest.fixture(autouse=True)
def _auth_resolved(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project: _RESOLVED,
    )


class TestHandleVariableGet:
    def test_existing_variable_returns_value(self, monkeypatch):
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable",
            lambda repo, name, *, token: "true",
        )
        outcome = handle_variable_get(_make_request())
        assert outcome.primary_success is True
        assert outcome.result_payload == {
            "repo": "upyoke/yoke",
            "name": "YOKE_PULUMI_CI_ENABLED",
            "exists": True,
            "value": "true",
        }

    def test_absent_variable_reports_exists_false(self, monkeypatch):
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable",
            lambda repo, name, *, token: None,
        )
        outcome = handle_variable_get(_make_request())
        assert outcome.primary_success is True
        assert outcome.result_payload["exists"] is False
        assert outcome.result_payload["value"] is None

    def test_transport_error_maps_to_typed_failure(self, monkeypatch):
        def _boom(repo, name, *, token):
            raise RestTransportError("GET /actions/variables exploded")

        monkeypatch.setattr(github_variables_rest, "get_repo_variable", _boom)
        outcome = handle_variable_get(_make_request())
        assert outcome.primary_success is False
        assert outcome.error.code == "rest_transport_error"

    def test_non_global_target_rejected(self):
        outcome = handle_variable_get(_make_request(target_kind="item"))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"

    def test_bad_repo_slug_rejected(self):
        outcome = handle_variable_get(
            _make_request({"repo": "no-slash", "name": "X"})
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"


class TestRestGetter:
    def _respond(self, monkeypatch, response=None, exc=None):
        def fake_request(req: RestRequest, *, token: str, timeout_seconds=30.0):
            assert req.method == "GET"
            assert req.path == (
                "/repos/upyoke/yoke/actions/variables/GATE"
            )
            if exc is not None:
                raise exc
            return response

        monkeypatch.setattr(
            github_variables_rest, "request_with_retry", fake_request,
        )

    def test_get_returns_value(self, monkeypatch):
        self._respond(monkeypatch, RestResponse(
            status=200, headers={}, body={"name": "GATE", "value": "true"},
        ))
        assert github_variables_rest.get_repo_variable(
            "upyoke/yoke", "GATE", token="t",
        ) == "true"

    def test_get_absent_returns_none(self, monkeypatch):
        self._respond(monkeypatch, exc=RestNotFoundError("404"))
        assert github_variables_rest.get_repo_variable(
            "upyoke/yoke", "GATE", token="t",
        ) is None

    def test_get_non_dict_body_returns_none(self, monkeypatch):
        self._respond(monkeypatch, RestResponse(status=200, headers={}, body=""))
        assert github_variables_rest.get_repo_variable(
            "upyoke/yoke", "GATE", token="t",
        ) is None


def test_registration_shape_matches_set_family():
    entry = github_actions_get.REGISTRATIONS[0]
    assert entry["function_id"] == "github_actions.variable.get"
    assert entry["side_effects"] == []  # read-only
    assert entry["target_kinds"] == ["global"]
    set_entry = github_actions_set.REGISTRATIONS[-1]
    assert entry["guardrails"] == set_entry["guardrails"]


if __name__ == "__main__":  # pragma: no cover - manual run
    raise SystemExit(pytest.main([__file__, "-q"]))
