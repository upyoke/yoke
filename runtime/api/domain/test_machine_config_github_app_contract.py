from __future__ import annotations

import pytest

from yoke_contracts.machine_config import schema as contract


def test_github_app_authorization_config_is_valid_without_env_connection() -> None:
    payload = {
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "web_url": contract.DEFAULT_GITHUB_WEB_URL,
            "app_slug": "yoke",
            "app_id": 42,
            "client_id": "Iv1.example",
            "profile_source": contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
            "authorization": {
                "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "refresh_credential_ref": "~/.yoke/secrets/github.user-refresh",
                "github_user_id": 1001,
                "login": "machine-user",
                "status": "authorized",
            },
        },
    }

    assert contract.validate_payload(payload) == []


def test_github_github_auth_machine_config_is_rejected() -> None:
    payload = {
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "credential_source": {
                "kind": "token_file",
                "path": "~/.yoke/secrets/github.token",
            },
        },
    }

    codes = {issue.code for issue in contract.validate_payload(payload)}

    assert "github_key_invalid" in codes
    assert "github_authorization_required" in codes


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("api_url", "http://api.github.example", "github_api_url_invalid"),
        ("api_url", "https://user@api.github.example", "github_api_url_invalid"),
        ("web_url", "https://github.example?next=evil", "github_web_url_invalid"),
    ],
)
def test_github_app_config_rejects_unsafe_endpoints(
    key: str, value: str, code: str,
) -> None:
    payload = contract.canonical_example_payload()
    payload["github"][key] = value

    codes = {issue.code for issue in contract.validate_payload(payload)}

    assert code in codes


@pytest.mark.parametrize(
    ("section", "key", "code"),
    [
        ("github", "app_id", "github_app_id_invalid"),
        ("authorization", "github_user_id", "github_authorization_user_id_invalid"),
        ("installation", "installation_id", "github_installation_id_invalid"),
        ("installation", "account_id", "github_installation_account_id_invalid"),
        ("repository", "repository_id", "github_repository_id_invalid"),
        ("repository", "installation_id", "github_repository_installation_id_invalid"),
    ],
)
def test_github_app_config_rejects_boolean_ids(
    section: str, key: str, code: str,
) -> None:
    github = {
        "api_url": contract.DEFAULT_GITHUB_API_URL,
        "web_url": contract.DEFAULT_GITHUB_WEB_URL,
        "app_slug": "yoke",
        "app_id": 5,
        "client_id": "Iv1.example",
        "profile_source": contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": "~/.yoke/secrets/github-app-user.json",
            "status": "authorized",
            "github_user_id": 1,
        },
        "installations": [{
            "installation_id": 2, "account_id": 3,
            "account_login": "octo-org", "repository_selection": "selected",
        }],
        "repositories": [{
            "repository_id": 4, "installation_id": 2,
            "full_name": "octo-org/app",
        }],
    }
    targets = {
        "github": github,
        "authorization": github["authorization"],
        "installation": github["installations"][0],
        "repository": github["repositories"][0],
    }
    targets[section][key] = True

    codes = {
        issue.code for issue in contract.validate_payload({
            "schema_version": 1, "github": github,
        })
    }

    assert code in codes


def test_github_app_config_rejects_unsafe_app_slug() -> None:
    payload = contract.canonical_example_payload()
    payload["github"]["app_slug"] = "../../install?next=evil"

    codes = {issue.code for issue in contract.validate_payload(payload)}

    assert "github_app_slug_invalid" in codes
