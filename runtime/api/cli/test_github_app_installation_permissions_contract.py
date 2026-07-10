from __future__ import annotations

import pytest

from yoke_contracts import github_app_installation_permissions as contract


def test_required_repository_permissions_match_onboarding_copy() -> None:
    assert contract.required_repository_permission_lines() == (
        "Actions: write",
        "Checks: read",
        "Contents: write",
        "Issues: write",
        "Metadata: read",
        "Pull requests: write",
        "Secrets: write",
        "Variables: write",
        "Workflows: write",
    )


def test_installation_permission_evaluator_accepts_write_for_read() -> None:
    granted = {
        permission.key: "write"
        for permission in contract.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    }
    evaluation = contract.evaluate_installation_repository_permissions(granted)
    assert evaluation["ok"] is True


def test_permission_level_mapping_is_derived_from_labeled_contract() -> None:
    expected = {
        permission.key: permission.access
        for permission in contract.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    }

    assert dict(contract.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS) == expected


def test_unknown_required_permission_level_never_passes() -> None:
    assert contract.permission_level_satisfies("write", "owner") is False
    assert contract.permission_level_satisfies("owner", "read") is False


def test_operation_permission_maps_are_immutable_and_exact() -> None:
    assert dict(contract.GITHUB_METADATA_READ_PERMISSION_LEVELS) == {
        "metadata": "read",
    }
    assert dict(contract.GITHUB_ISSUES_WRITE_PERMISSION_LEVELS) == {
        "issues": "write",
    }
    assert dict(contract.GITHUB_ACTIONS_READ_PERMISSION_LEVELS) == {
        "actions": "read",
    }
    assert (
        contract.GITHUB_ENVIRONMENT_WRITE_PERMISSION_LEVELS
        is contract.GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS
    )
    with pytest.raises(TypeError):
        contract.GITHUB_ISSUES_WRITE_PERMISSION_LEVELS["issues"] = "read"  # type: ignore[index]
