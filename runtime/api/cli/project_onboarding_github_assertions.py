"""GitHub automation-preview assertions shared by onboarding CLI tests."""

from __future__ import annotations

from typing import Any

EXPECTED_GITHUB_PREVIEW_CATEGORIES = {
    "labels", "issue_templates", "pull_request_templates", "actions_variables",
    "actions_secrets", "branch_protection", "environment_protection",
    "runner_administration",
}


def assert_github_preview(payload: dict[str, Any], *, enabled: bool) -> None:
    preview = payload["automation_preview"]
    assert preview["github"]["enabled"] is enabled
    assert {
        write["category"] for write in preview["github"]["writes"]
    } == EXPECTED_GITHUB_PREVIEW_CATEGORIES
    expected = {"pending-app-installation" if enabled else "skipped-by-adoption-choice"}
    if enabled:
        expected.add("requires-optional-administration")
    assert {write["status"] for write in preview["github"]["writes"]} == expected


__all__ = ["EXPECTED_GITHUB_PREVIEW_CATEGORIES", "assert_github_preview"]
