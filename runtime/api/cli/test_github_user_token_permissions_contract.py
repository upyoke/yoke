from __future__ import annotations

from yoke_contracts import github_user_token_permissions as contract


def test_required_repository_token_permissions_match_onboarding_copy() -> None:
    assert contract.repository_permission_lines() == (
        "Actions: write",
        "Administration: write",
        "Contents: write",
        "Environments: write",
        "Issues: write",
        "Metadata: read",
        "Pull requests: write",
        "Secrets: write",
        "Variables: write",
        "Workflows: write",
    )


def test_scoped_token_scopes_require_repo_and_workflow() -> None:
    assert contract.evaluate_scoped_token_scopes(["repo", "workflow"])["ok"] is True
    missing = contract.evaluate_scoped_token_scopes(["repo"])
    assert missing["ok"] is False
    assert missing["missing"] == ["workflow"]


def test_repository_token_permission_evaluator_accepts_write_for_read() -> None:
    granted = {
        permission.key: "write"
        for permission in contract.REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS
    }
    assert contract.evaluate_repository_permissions(granted)["ok"] is True


def test_scoped_token_can_create_repos_repo_scope_creates_private() -> None:
    result = contract.scoped_token_can_create_repos(["repo", "workflow"])
    assert result["can_create"] is True
    assert result["create_private"] is True
    assert result["basis"] == "scope:repo"


def test_scoped_token_can_create_repos_public_repo_scope_creates_public_only() -> None:
    result = contract.scoped_token_can_create_repos(["public_repo"])
    assert result["can_create"] is True
    assert result["create_private"] is False
    assert result["basis"] == "scope:public_repo"


def test_scoped_token_can_create_repos_no_repo_scope_cannot_create() -> None:
    result = contract.scoped_token_can_create_repos(["workflow", "read:org"])
    assert result["can_create"] is False
    assert result["create_private"] is False
    assert result["basis"] == "scope:none"


def test_scoped_token_can_create_repos_empty_scopes_cannot_create() -> None:
    assert contract.scoped_token_can_create_repos([])["can_create"] is False
