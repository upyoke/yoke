"""Canonical safety bounds for GitHub App binding metadata."""

from __future__ import annotations

import json
import urllib.parse

import pytest

from yoke_contracts.github_account_types import ACCOUNT_TYPES
from yoke_contracts.github_binding_metadata import (
    GitHubBindingMetadataError,
    validate_binding_metadata,
)
from yoke_contracts.github_origin import validate_github_api_endpoint
from yoke_core.domain import project_github_binding
from yoke_core.domain.github_app_user_verification import (
    GitHubUserVerificationError,
    VerifiedProjectGitHubBinding,
    verify_project_github_binding,
)


def _metadata(**overrides):
    values = {
        "installation_id": "12345",
        "account_id": "9988",
        "account_login": "Example_Org",
        "account_type": "organization",
        "repository_selection": "selected",
        "permissions": {"metadata": "read", "issues": "write"},
        "repository_id": "4567",
        "github_repo": "https://github.example/Example-Org/ExternalWebapp.git",
        "default_branch": "feature/safe-name",
        "installation_status": "active",
    }
    values.update(overrides)
    return values


def test_binding_metadata_is_canonical_and_immutable() -> None:
    metadata = validate_binding_metadata(**_metadata())

    assert metadata.account_type == "Organization"
    assert metadata.github_repo == "Example-Org/ExternalWebapp"
    assert metadata.permissions == {"metadata": "read", "issues": "write"}
    with pytest.raises(TypeError):
        metadata.permissions["issues"] = "read"  # type: ignore[index]


@pytest.mark.parametrize("account_type", sorted(ACCOUNT_TYPES))
def test_every_canonical_installation_account_type_is_accepted(
    account_type,
) -> None:
    metadata = validate_binding_metadata(
        **_metadata(account_type=account_type.casefold())
    )

    assert metadata.account_type == account_type


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "0"),
        ("installation_id", "1" * 21),
        ("account_login", "bad\x1b[red]"),
        ("account_login", "x" * 40),
        ("account_type", "Team"),
        ("repository_selection", "everything"),
        ("permissions", {"issues": "admin"}),
        ("permissions", {"bad\x1b": "write"}),
        ("github_repo", "owner/bad\nrepo"),
        ("default_branch", "-c core.sshCommand=evil"),
        ("default_branch", "feature/\u202ereversed"),
        ("default_branch", "feature/\ud800surrogate"),
        ("default_branch", "refs//main"),
        ("installation_status", "deleted"),
    ],
)
def test_binding_metadata_rejects_unsafe_or_unbounded_fields(field, value) -> None:
    with pytest.raises(GitHubBindingMetadataError):
        validate_binding_metadata(**_metadata(**{field: value}))


class _Response:
    def __init__(self, body, url: str) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


def _verification_opener(*, repository_name: str, default_branch: str):
    def open_request(request, timeout):
        del timeout
        path = urllib.parse.urlsplit(request.full_url).path
        if path == "/user":
            body = {"id": 77, "login": "octocat"}
        elif path == "/user/installations":
            body = {
                "installations": [
                    {
                        "id": 12345,
                        "account": {
                            "id": 9988,
                            "login": "Example_Org",
                            "type": "Organization",
                        },
                        "repository_selection": "selected",
                        "permissions": {"issues": "write"},
                        "suspended_at": None,
                    }
                ]
            }
        else:
            assert path == "/user/installations/12345/repositories"
            body = {
                "repositories": [
                    {
                        "id": 4567,
                        "full_name": repository_name,
                        "default_branch": default_branch,
                        "owner": {"id": 9988},
                    }
                ]
            }
        return _Response(body, request.full_url)

    return open_request


def test_user_verification_normalizes_repository_before_returning() -> None:
    verified = verify_project_github_binding(
        installation_id="12345",
        repository_id="4567",
        expected_github_repo="example-org/externalwebapp",
        expected_api_url="https://api.github.com",
        github_user_access_token="user-secret",
        endpoint=validate_github_api_endpoint("https://api.github.com"),
        opener=_verification_opener(
            repository_name="https://github.com/Example-Org/ExternalWebapp.git",
            default_branch="main",
        ),
    )

    assert verified.github_repo == "Example-Org/ExternalWebapp"


def test_user_verification_rejects_unsafe_default_branch() -> None:
    with pytest.raises(GitHubUserVerificationError, match="default branch"):
        verify_project_github_binding(
            installation_id="12345",
            repository_id="4567",
            expected_github_repo="example-org/externalwebapp",
            expected_api_url="https://api.github.com",
            github_user_access_token="user-secret",
            endpoint=validate_github_api_endpoint("https://api.github.com"),
            opener=_verification_opener(
                repository_name="Example-Org/ExternalWebapp",
                default_branch="-c core.sshCommand=evil",
            ),
        )


def test_persistence_revalidates_typed_verifier_output_before_connect(
    monkeypatch,
) -> None:
    verified = VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="Example-Org",
        account_type="Organization",
        repository_selection="selected",
        permissions={"issues": "write"},
        repository_id="4567",
        github_repo="Example-Org/ExternalWebapp",
        default_branch="bad\x1bbranch",
    )
    connected = False

    def unexpected_connect(_db_path):
        nonlocal connected
        connected = True
        raise AssertionError("invalid metadata must fail before database access")

    monkeypatch.setattr(project_github_binding, "connect", unexpected_connect)
    with pytest.raises(
        project_github_binding.ProjectGithubBindingError,
        match="default branch",
    ):
        project_github_binding._store_verified_project_repo_binding(
            "externalwebapp",
            verified=verified,
        )

    assert connected is False
