from __future__ import annotations

from yoke_cli.config import github_machine_report
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
