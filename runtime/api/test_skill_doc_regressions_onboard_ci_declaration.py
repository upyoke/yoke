"""Onboard teaches which workflow may become the project's CI declaration.

The engine refuses a workflow the verification gate cannot start, but the
refusal only ever fires on a declaration someone already proposed. These
assertions keep the proposal itself honest: onboarding proposes the test
workflow only, and the verification doc names the triggers, the non-Actions
CI systems, and the merge-queue conditions its row creation enforces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARD_SKILL_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "onboard"
VERIFICATION_DOC = REPO_ROOT / ".yoke" / "docs" / "verification" / "index.md"


@pytest.fixture(scope="module")
def binding() -> str:
    return (ONBOARD_SKILL_DIR / "verification-binding.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def verification_doc() -> str:
    return VERIFICATION_DOC.read_text(encoding="utf-8")


def test_binding_proposes_the_test_workflow_only(binding: str) -> None:
    assert "Actions test workflow (never deploy/release)" in binding
    assert "`ci_workflow_file`" in binding


def test_non_actions_ci_systems_stay_on_the_local_command(
    verification_doc: str,
) -> None:
    for marker in ("Jenkins", "GitLab CI", "Bitbucket Pipelines"):
        assert marker in verification_doc
    assert "they are not `ci_workflow_file` declarations" in verification_doc


def test_the_declaration_names_the_triggers_the_gate_needs(
    verification_doc: str,
) -> None:
    assert "yoke_dispatch_id" in verification_doc
    assert "workflow_dispatch" in verification_doc
    assert "pull_request" in verification_doc
    assert ".github/workflows/" in verification_doc


def test_the_merge_queue_conditions_are_named(verification_doc: str) -> None:
    assert "Declaring `merge_queue` requires GitHub bound" in verification_doc
    assert "merge_group" in verification_doc
