"""Public diagnostic contract for project GitHub authorization."""

import pytest

from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)
from yoke_core.domain import project_github_auth as pga
from yoke_core.domain import project_github_auth_tokens
from yoke_core.domain import project_github_binding_payload


_ERROR_CLASSES = (
    pga.MissingCapability,
    pga.MissingRepoMetadata,
    pga.MissingRepoBinding,
    pga.MissingInstallation,
    pga.BindingUnavailable,
    pga.InstallationUnavailable,
    pga.MissingPermission,
    pga.MissingAppCredentials,
    pga.TokenMintFailed,
    pga.UserAuthorizationUnavailable,
    pga.InvalidToken,
    pga.TransportFailure,
)


@pytest.mark.parametrize("error_class", _ERROR_CLASSES)
def test_error_has_code_and_repair_hint(error_class):
    error = error_class("buzz", "test message")
    assert isinstance(error.code, str)
    assert "buzz" in pga.repair_command_hint(error, "buzz")


def test_public_surface_exports():
    expected = {
        "BindingUnavailable", "InstallationUnavailable", "InvalidToken",
        "MissingAppCredentials", "MissingCapability", "MissingInstallation",
        "MissingPermission", "MissingRepoBinding", "MissingRepoMetadata",
        "ProjectGithubAuth", "ProjectGithubAuthError", "TokenMintFailed",
        "TransportFailure", "UserAuthorizationUnavailable",
        "bind_local_github_user_token_provider", "repair_command_hint",
        "resolve_project_github_auth",
    }
    assert not expected - set(dir(pga))


def test_core_permission_consumer_uses_contract_mapping() -> None:
    assert (
        project_github_binding_payload
        .REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
        is REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
    )


def test_installation_contract_and_token_scope_are_separate() -> None:
    installation = project_github_auth_tokens.installation_contract_permissions({
        "issues": "read",
    })
    token = project_github_auth_tokens.scoped_installation_token_permissions({
        "issues": "read",
    })

    assert installation == dict(REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS)
    assert installation["issues"] == "write"
    assert token == {"metadata": "read", "issues": "read"}


def test_core_permission_consumers_reject_fictitious_admin_level() -> None:
    result = project_github_binding_payload.permission_status(
        {"contents": "admin"}, {"contents": "write"},
    )
    assert result["status"] == "missing"
    with pytest.raises(ValueError, match="valid access levels"):
        project_github_auth_tokens.scoped_installation_token_permissions({
            "administration": "admin",
        })
    with pytest.raises(ValueError, match="valid access levels"):
        project_github_auth_tokens.installation_contract_permissions({
            "administration": "admin",
        })


@pytest.mark.parametrize("required_level", ["admin", "none", "bogus", ""])
def test_binding_permission_status_rejects_unknown_required_levels(
    required_level: str,
) -> None:
    with pytest.raises(ValueError, match="exactly read or write"):
        project_github_binding_payload.permission_status(
            {"contents": "write"}, {"contents": required_level},
        )
