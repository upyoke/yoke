"""Transport-safe Pulumi GitHub App authority tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_cli.transport import pulumi_github_authority as authority
from yoke_contracts.api.function_call import FunctionCallResponse


def _response(*, permissions=None, repo="upyoke/platform"):
    return FunctionCallResponse(
        success=True,
        function="projects.github_binding.status",
        version="v1",
        request_id="request",
        result={
            "project": "platform",
            "binding": {
                "status": "active",
                "github_repo": repo,
                "api_url": "https://api.github.com",
            },
            "installation": {
                "status": "active",
                "permissions": permissions or {
                    "metadata": "read",
                    "actions_variables": "write",
                },
            },
        },
    )


def test_https_loader_verifies_binding_permissions_and_service_profile(
    monkeypatch,
):
    seen = {}

    def dispatch(**kwargs):
        seen["dispatch"] = kwargs
        return _response()

    def token_loader(**kwargs):
        seen["token"] = kwargs
        return SimpleNamespace(access_token="github-user-token")

    monkeypatch.setattr(
        authority,
        "resolve_https_connection",
        lambda: SimpleNamespace(api_url="https://api.upyoke.com"),
    )
    loader = authority.build_pulumi_github_auth_loader(
        session_id="session", dispatch=dispatch, token_loader=token_loader
    )
    result = loader(
        "platform",
        required_permissions={
            "metadata": "read",
            "actions_variables": "write",
        },
    )
    assert result.repo == "upyoke/platform"
    assert result.token == "github-user-token"
    assert seen["dispatch"]["payload"] == {"project": "platform"}
    assert seen["token"] == {
        "service_api_url": "https://api.upyoke.com",
        "local_connection_selected": False,
    }


def test_loader_rejects_missing_permission_before_token_refresh(monkeypatch):
    token_called = False

    def token_loader(**kwargs):
        nonlocal token_called
        token_called = True
        return SimpleNamespace(access_token="must-not-load")

    loader = authority.build_pulumi_github_auth_loader(
        session_id=None,
        dispatch=lambda **kwargs: _response(
            permissions={"metadata": "read", "actions_variables": "read"}
        ),
        token_loader=token_loader,
    )
    with pytest.raises(
        authority.PulumiGithubAuthorityError,
        match="actions_variables",
    ) as raised:
        loader(
            "platform",
            required_permissions={"actions_variables": "write"},
        )
    assert raised.value.pulumi_safe_message == str(raised.value)
    assert token_called is False


def test_token_failure_does_not_echo_sensitive_cause(monkeypatch):
    monkeypatch.setattr(
        authority, "resolve_https_connection", lambda: None
    )
    loader = authority.build_pulumi_github_auth_loader(
        session_id=None,
        dispatch=lambda **kwargs: _response(),
        token_loader=lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("ghu_sensitive-token")
        ),
    )
    with pytest.raises(authority.PulumiGithubAuthorityError) as raised:
        loader(
            "platform", required_permissions={"actions_variables": "write"}
        )
    assert "ghu_sensitive-token" not in str(raised.value)
    assert "yoke github status" in str(raised.value)


def test_actions_uses_consistent_ambient_repository_token(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "actions-token")
    monkeypatch.setenv("RUNNER_FLEET_GITHUB_TOKEN", "actions-token")
    loader = authority.build_pulumi_github_auth_loader(
        session_id=None,
        dispatch=lambda **kwargs: _response(),
        token_loader=lambda **kwargs: pytest.fail("refreshed machine token"),
    )
    result = loader(
        "platform", required_permissions={"actions_variables": "write"}
    )
    assert result.repo == "upyoke/platform"
    assert result.token == "actions-token"
