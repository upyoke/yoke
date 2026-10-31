"""User authority never silently becomes installation authority."""
# ruff: noqa: F811

from functools import partial
from unittest.mock import Mock

import pytest

from runtime.api.domain.project_github_auth_test_support import (
    _minted,
    app_bound_db as app_bound_db,
    control_plane_config as control_plane_config,
    db_path as db_path,
)
from yoke_core.domain import project_github_auth as auth
from yoke_core.domain.handlers.github_pr_create import handle_pr_create
from yoke_contracts.api.function_call import (
    ActorContext, FunctionCallRequest, TargetRef,
)


@pytest.mark.parametrize("authority", [auth.GITHUB_AUTHORITY_USER, "unknown"])
def test_unbound_user_authority_refuses_before_credentials(
    app_bound_db, monkeypatch, authority,
):
    minter = Mock(return_value=_minted())
    credentials = Mock(side_effect=AssertionError("must not read credentials"))
    monkeypatch.setattr(auth, "read_app_credentials", credentials)
    with pytest.raises(auth.UserAuthorizationUnbound) as caught:
        auth.resolve_project_github_auth(
            "yoke", db_path=app_bound_db, token_minter=minter,
            required_authority=authority,
        )
    assert caught.value.code == "user_authorization_unbound"
    assert "attributed to a person" in str(caught.value)
    assert "yoke merge" in auth.repair_command_hint(caught.value, "yoke")
    minter.assert_not_called()
    credentials.assert_not_called()


def test_unbound_installation_authority_mints_once(app_bound_db):
    minter = Mock(return_value=_minted())
    result = auth.resolve_project_github_auth(
        "yoke", db_path=app_bound_db, token_minter=minter,
        required_authority=auth.GITHUB_AUTHORITY_INSTALLATION,
    )
    assert result.token == "ghs_install"
    assert result.token_source == auth.GITHUB_AUTHORITY_INSTALLATION
    minter.assert_called_once()


def test_bound_user_provider_wins_without_minting(app_bound_db):
    minter = Mock(return_value=_minted())
    with auth.bind_local_github_user_token_provider(
        lambda: "u-token", api_url="https://api.github.com",
    ):
        result = auth.resolve_project_github_auth(
            "yoke", db_path=app_bound_db, token_minter=minter,
            required_authority=auth.GITHUB_AUTHORITY_USER,
        )
    assert result.token == "u-token"
    assert result.token_source == auth.GITHUB_AUTHORITY_USER
    minter.assert_not_called()


def request(head):
    return FunctionCallRequest(
        function="github.pr.create", actor=ActorContext(session_id="test"),
        target=TargetRef(kind="global"),
        payload={"project": "yoke", "title": "Install Yoke", "head": head},
    )


def test_installer_relay_uses_real_resolver_and_installation_token(
    app_bound_db, monkeypatch,
):
    minter = Mock(return_value=_minted())
    monkeypatch.setattr(auth, "resolve_project_github_auth", partial(
        auth.resolve_project_github_auth, db_path=app_bound_db, token_minter=minter,
    ))
    rest = Mock(return_value={"number": 1, "url": "https://github.com/o/r/pull/1"})
    monkeypatch.setattr(
        "yoke_core.domain.github_pr_rest.create_pull_request", rest,
    )
    result = handle_pr_create(request("yoke-install/abc123def456"))
    assert result.primary_success is True
    minter.assert_called_once()
    rest.assert_called_once_with(
        "upyoke/yoke", title="Install Yoke", head="yoke-install/abc123def456",
        base="main", body=None, draft=False, token="ghs_install",
    )


def test_non_installer_head_refuses_before_auth_or_rest(monkeypatch):
    resolver = Mock(side_effect=AssertionError("must not resolve auth"))
    rest = Mock(side_effect=AssertionError("must not call REST"))
    monkeypatch.setattr(auth, "resolve_project_github_auth", resolver)
    monkeypatch.setattr("yoke_core.domain.github_pr_rest.create_pull_request", rest)
    result = handle_pr_create(request("feature/change"))
    assert result.primary_success is False
    assert result.error.code == "pr_create_not_install_proposal"
    assert "yoke merge" in result.error.message
    resolver.assert_not_called()
    rest.assert_not_called()
