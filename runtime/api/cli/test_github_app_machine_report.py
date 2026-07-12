from __future__ import annotations

import json

import pytest

from yoke_cli.config import github_machine_report
from yoke_cli.config import github_machine
from yoke_cli.config import github_machine_state
from yoke_contracts import github_app_installation_permissions
from yoke_contracts import github_origin


def test_human_report_renders_permission_repair_details() -> None:
    rendered = github_machine_report.render_human({
        "configured": True,
        "ok": False,
        "ready": False,
        "permissions": {
            "ok": False,
            "items": [{
                "account_login": "octo-org",
                "evaluation": {"missing": [{
                    "key": "workflows",
                    "required": "write",
                    "granted": "read",
                }]},
            }],
        },
        "issues": [{
            "code": "github_app_installation_permissions_incomplete",
            "message": "permissions are incomplete",
            "hint": "Update the App installation permissions.",
        }],
    })

    assert "missing_permission: octo-org workflows:write (granted=read)" in rendered
    assert "hint: Update the App installation permissions." in rendered


def test_json_access_exposes_only_public_repository_metadata() -> None:
    report = github_machine_report.connected(
        None,
        {
            "api_url": "https://api.github.com",
            "repositories": [{
                "repository_id": 456,
                "full_name": "octo-org/app",
                "default_branch": "main",
                "installation_id": 123,
                "access_token": "must-not-leak",
                "refresh_credential_ref": "/must/not/leak",
            }],
        },
        authorization={"present": True},
        checked=True,
        live_check_ok=True,
        permissions={"usable": True},
        issues=[],
    )

    assert report["access"]["repos"] == ["octo-org/app"]
    assert report["access"]["repositories"] == [{
        "repository_id": 456,
        "full_name": "octo-org/app",
        "default_branch": "main",
        "installation_id": 123,
    }]
    serialized = json.dumps(report)
    assert "must-not-leak" not in serialized
    assert "/must/not/leak" not in serialized

    rendered = github_machine_report.render_human(report)
    assert "repositories: 1 accessible" in rendered
    assert "octo-org/app" in rendered
    assert "repository_id" not in rendered


def test_install_url_rejects_unsafe_app_slug() -> None:
    endpoint_pair = github_origin.validate_github_endpoint_pair(
        "https://api.github.com", "https://github.com",
    )

    try:
        endpoint_pair.app_install_url("../../settings?next=evil")
    except github_origin.GitHubApiOriginError as exc:
        assert "slug" in str(exc)
    else:
        raise AssertionError("expected unsafe App slug rejection")


def test_permission_aggregate_accepts_one_healthy_installation() -> None:
    granted = dict(
        github_app_installation_permissions
        .REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
    )
    result = github_machine_state._permission_report([
        {
            "installation_id": 1, "account_login": "paused",
            "suspended": True, "permissions": granted,
        },
        {
            "installation_id": 2, "account_login": "healthy",
            "suspended": False, "permissions": granted,
        },
    ])

    assert result["ok"] is True
    assert result["usable"] is True


def test_malformed_cached_fields_return_validation_issues(tmp_path) -> None:
    report = github_machine_state.connected_report(
        config_path=tmp_path / "config.json",
        github={
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "app_slug": "yoke",
            "client_id": "Iv1.local",
            "authorization": "not-an-object",
            "installations": {"not": "a-list"},
            "repositories": "not-a-list",
        },
        progress=[],
        checked=False,
    )

    codes = {item["code"] for item in report["issues"]}
    assert report["ok"] is False
    assert "github_authorization_required" in codes
    assert "github_installations_invalid" in codes
    assert "github_repositories_invalid" in codes


def _cached_github(*, html_url: str, app_id: int = 123,
                   app_slug: str = "yoke") -> dict:
    granted = dict(
        github_app_installation_permissions
        .REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
    )
    return {
        "api_url": "https://api.github.com",
        "web_url": "https://github.com",
        "app_slug": "yoke",
        "app_id": 123,
        "client_id": "Iv1.local",
        "authorization": {
            "kind": "github_app_user_authorization",
            "status": "authorized",
            "refresh_credential_ref": "/private/github-refresh.json",
        },
        "installations": [{
            "installation_id": 123,
            "app_id": app_id,
            "app_slug": app_slug,
            "account_login": "octo-org",
            "account_type": "Organization",
            "repository_selection": "selected",
            "suspended": False,
            "permissions": granted,
            "html_url": html_url,
        }],
        "repositories": [{
            "repository_id": 456,
            "installation_id": 123,
            "full_name": "octo-org/app",
            "default_branch": "main",
        }],
    }


def test_offline_report_drops_control_bearing_cached_identity_fields(
    tmp_path,
) -> None:
    github = _cached_github(
        html_url=(
            "https://github.com/organizations/octo-org/"
            "settings/installations/123"
        ),
    )
    github["authorization"]["login"] = "octocat\x1b]2;spoof"
    github["installations"][0]["account_login"] = "org\x9b31m"
    github["repositories"][0]["full_name"] = "org/repo\x07"

    report = github_machine_state.connected_report(
        config_path=tmp_path / "config.json",
        github=github,
        progress=[],
        checked=False,
    )
    rendered = github_machine_report.render_human(report)

    assert report["identity"]["login"] == ""
    assert report["access"]["installations"] == []
    assert report["access"]["repositories"] == []
    assert "spoof" not in rendered
    assert all(ord(char) >= 32 or char == "\n" for char in rendered)


@pytest.mark.parametrize("unsafe_url", [
    "https://attacker.example/settings/installations/123",
    "javascript:alert(1)",
    "https://github.com/settings/installations/999",
])
def test_offline_report_omits_unsafe_cached_installation_url(
    tmp_path, unsafe_url: str,
) -> None:
    report = github_machine_state.connected_report(
        config_path=tmp_path / "config.json",
        github=_cached_github(html_url=unsafe_url),
        progress=[], checked=False,
    )

    assert "settings_url" not in report["permissions"]["items"][0]
    assert "html_url" not in report["access"]["installations"][0]
    assert unsafe_url not in github_machine_report.render_human(report)


@pytest.mark.parametrize("app_id,app_slug", [
    (999, "yoke"),
    (123, "Yoke"),
])
def test_offline_status_rejects_cached_installation_for_different_app(
    tmp_path, app_id: int, app_slug: str,
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "schema_version": 1,
        "github": _cached_github(
            html_url=(
                "https://github.com/organizations/octo-org/"
                "settings/installations/123"
            ),
            app_id=app_id,
            app_slug=app_slug,
        ),
    }), encoding="utf-8")

    report = github_machine.status(config_path=config, check=False)

    assert report["ready"] is False
    assert report["access"]["repo_count"] == 0
    assert report["access"]["repositories"] == []
    assert "github_cached_installation_app_mismatch" in {
        item["code"] for item in report["issues"]
    }
