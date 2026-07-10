"""Tests for the ``github_actions.secret.set`` / ``.variable.set`` handlers.

REST calls are mocked at the domain-helper seam (the same monkeypatch
pattern test_github_actions_check_ci uses); the secret-hygiene tests
assert the plaintext value never leaks into result payloads or error
messages.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest

from yoke_core.domain.handlers import github_actions_set
from yoke_core.domain.handlers.github_actions_set import (
    handle_secret_set,
    handle_variable_set,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


_SECRET_VALUE = "shh-rotated-access-key"

_RESOLVED = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghs_test_token",
)


def _make_request(
    function: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
    include_project: bool = True,
) -> FunctionCallRequest:
    if payload is None:
        payload = {
            "repo": "upyoke/yoke",
            "name": "YOKE_CI_TEST",
            "value": _SECRET_VALUE,
        }
    payload = dict(payload)
    if include_project:
        payload.setdefault("project", "yoke")
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


def _secret_request(payload=None, **kw):
    return _make_request("github_actions.secret.set", payload, **kw)


def _variable_request(payload=None, **kw):
    return _make_request("github_actions.variable.set", payload, **kw)


@pytest.fixture
def _resolver_ok(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **kw: _RESOLVED,
    )


class TestSecretSet:
    def test_rejects_missing_project(self):
        outcome = handle_secret_set(_secret_request(include_project=False))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"
        assert "project" in outcome.error.message

    def test_rejects_non_global_target(self):
        outcome = handle_secret_set(_secret_request(target_kind="item"))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"

    def test_rejects_repo_without_slash(self, _resolver_ok):
        outcome = handle_secret_set(
            _secret_request({"repo": "no-slash", "name": "X", "value": "v"})
        )
        assert not outcome.primary_success
        assert "owner/name" in outcome.error.message

    def test_rejects_missing_value(self):
        outcome = handle_secret_set(
            _secret_request({"repo": "o/r", "name": "X"})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"
        assert "value" in outcome.error.message

    def test_validation_error_does_not_echo_value(self):
        # A wrong-typed value must not be reflected back by pydantic.
        outcome = handle_secret_set(
            _secret_request({"repo": "o/r", "name": "X", "value": 987654321})
        )
        assert not outcome.primary_success
        assert "987654321" not in outcome.error.message

    def test_sets_secret_through_sealed_box_helper(self, monkeypatch, _resolver_ok):
        calls = []

        def fake_set(repo, name, value, *, token):
            calls.append({"repo": repo, "name": name, "value": value, "token": token})

        monkeypatch.setattr(
            "yoke_core.domain.github_secrets_rest.set_repo_secret", fake_set,
        )
        outcome = handle_secret_set(_secret_request())
        assert outcome.primary_success
        assert calls == [{
            "repo": "upyoke/yoke",
            "name": "YOKE_CI_TEST",
            "value": _SECRET_VALUE,
            "token": "ghs_test_token",
        }]
        assert outcome.result_payload == {
            "repo": "upyoke/yoke",
            "name": "YOKE_CI_TEST",
            "result": "set",
        }

    def test_result_payload_never_carries_value(self, monkeypatch, _resolver_ok):
        monkeypatch.setattr(
            "yoke_core.domain.github_secrets_rest.set_repo_secret",
            lambda *a, **kw: None,
        )
        outcome = handle_secret_set(_secret_request())
        assert _SECRET_VALUE not in json.dumps(outcome.result_payload)

    def test_transport_error_does_not_echo_value(self, monkeypatch, _resolver_ok):
        from yoke_core.domain.gh_rest_transport import RestServerError

        def _raise(*a, **kw):
            raise RestServerError("HTTP 503: brief outage", status=503)

        monkeypatch.setattr(
            "yoke_core.domain.github_secrets_rest.set_repo_secret", _raise,
        )
        outcome = handle_secret_set(_secret_request())
        assert not outcome.primary_success
        assert outcome.error.code == "rest_transport_error"
        assert _SECRET_VALUE not in outcome.error.message

    def test_missing_app_credentials_surface_as_auth_error(self, monkeypatch):
        from yoke_core.domain.project_github_auth import MissingAppCredentials

        def _raise(project, **kw):
            raise MissingAppCredentials(project, "App credentials missing")

        monkeypatch.setattr(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            _raise,
        )
        outcome = handle_secret_set(_secret_request())
        assert not outcome.primary_success
        assert outcome.error.code == "project_auth_error"


class TestVariableSet:
    def test_rejects_missing_project(self):
        outcome = handle_variable_set(_variable_request(include_project=False))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"
        assert "project" in outcome.error.message

    def test_rejects_non_global_target(self):
        outcome = handle_variable_set(_variable_request(target_kind="item"))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"

    def test_rejects_repo_without_slash(self, _resolver_ok):
        outcome = handle_variable_set(
            _variable_request({"repo": "no-slash", "name": "X", "value": "v"})
        )
        assert not outcome.primary_success
        assert "owner/name" in outcome.error.message

    @pytest.mark.parametrize("upsert_outcome", ["created", "updated"])
    def test_sets_variable_and_reports_outcome(
        self, monkeypatch, _resolver_ok, upsert_outcome,
    ):
        calls = []

        def fake_set(repo, name, value, *, token):
            calls.append({"repo": repo, "name": name, "value": value, "token": token})
            return upsert_outcome

        monkeypatch.setattr(
            "yoke_core.domain.github_variables_rest.set_repo_variable", fake_set,
        )
        outcome = handle_variable_set(
            _variable_request({
                "repo": "upyoke/yoke",
                "name": "YOKE_PULUMI_CI_ENABLED",
                "value": "false",
            })
        )
        assert outcome.primary_success
        assert calls[0]["value"] == "false"
        assert calls[0]["token"] == "ghs_test_token"
        assert outcome.result_payload == {
            "repo": "upyoke/yoke",
            "name": "YOKE_PULUMI_CI_ENABLED",
            "result": upsert_outcome,
        }

    def test_transport_error_surfaces(self, monkeypatch, _resolver_ok):
        from yoke_core.domain.gh_rest_transport import RestAuthError

        def _raise(*a, **kw):
            raise RestAuthError("HTTP 403: forbidden", status=403)

        monkeypatch.setattr(
            "yoke_core.domain.github_variables_rest.set_repo_variable", _raise,
        )
        outcome = handle_variable_set(_variable_request())
        assert not outcome.primary_success
        assert outcome.error.code == "rest_transport_error"

    def test_missing_app_credentials_surface_as_auth_error(self, monkeypatch):
        from yoke_core.domain.project_github_auth import MissingAppCredentials

        def _raise(project, **kw):
            raise MissingAppCredentials(project, "App credentials missing")

        monkeypatch.setattr(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            _raise,
        )
        outcome = handle_variable_set(_variable_request())
        assert not outcome.primary_success
        assert outcome.error.code == "project_auth_error"


class TestRegistration:
    def test_registration_entries_present(self):
        ids = {entry["function_id"] for entry in github_actions_set.REGISTRATIONS}
        assert ids == {
            "github_actions.secret.set",
            "github_actions.variable.set",
        }

    def test_registrations_are_global_targeted(self):
        for entry in github_actions_set.REGISTRATIONS:
            assert entry["target_kinds"] == ["global"]
            assert entry["claim_required_kind"] is None
