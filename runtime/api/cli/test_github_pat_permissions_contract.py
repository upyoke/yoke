from __future__ import annotations

from yoke_contracts import github_pat_permissions as contract


def test_required_fine_grained_pat_permissions_match_onboarding_copy() -> None:
    assert contract.fine_grained_permission_lines() == (
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


def test_classic_pat_scopes_require_repo_and_workflow() -> None:
    assert contract.evaluate_classic_scopes(["repo", "workflow"])["ok"] is True
    missing = contract.evaluate_classic_scopes(["repo"])
    assert missing["ok"] is False
    assert missing["missing"] == ["workflow"]


def test_fine_grained_permission_evaluator_accepts_write_for_read() -> None:
    granted = {
        permission.key: "write"
        for permission in contract.REQUIRED_FINE_GRAINED_PAT_PERMISSIONS
    }
    assert contract.evaluate_fine_grained_permissions(granted)["ok"] is True


def test_classic_can_create_repos_repo_scope_creates_private() -> None:
    result = contract.classic_can_create_repos(["repo", "workflow"])
    assert result["can_create"] is True
    assert result["create_private"] is True
    assert result["basis"] == "classic_scope:repo"


def test_classic_can_create_repos_public_repo_scope_creates_public_only() -> None:
    result = contract.classic_can_create_repos(["public_repo"])
    assert result["can_create"] is True
    assert result["create_private"] is False
    assert result["basis"] == "classic_scope:public_repo"


def test_classic_can_create_repos_no_repo_scope_cannot_create() -> None:
    result = contract.classic_can_create_repos(["workflow", "read:org"])
    assert result["can_create"] is False
    assert result["create_private"] is False
    assert result["basis"] == "classic_scope:none"


def test_classic_can_create_repos_empty_scopes_cannot_create() -> None:
    assert contract.classic_can_create_repos([])["can_create"] is False
