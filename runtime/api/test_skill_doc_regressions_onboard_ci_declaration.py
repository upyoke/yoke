"""Onboard teaches which workflow may become the project's CI declaration.

The engine refuses a workflow the verification gate cannot start, but the
refusal only ever fires on a declaration someone already proposed. These
assertions keep the proposal itself honest: the survey classifies workflows by
purpose, the profile proposes the test workflow only, and the merge queue is
offered only under the conditions its row creation enforces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARD_SKILL_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "onboard"


def _skill(name: str) -> str:
    return (ONBOARD_SKILL_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def survey() -> str:
    return _skill("strategy-conversation.md")


@pytest.fixture(scope="module")
def profile() -> str:
    return _skill("profile-and-scaffold.md")


@pytest.fixture(scope="module")
def binding() -> str:
    return _skill("hosting-and-environments.md")


def test_survey_enumerates_and_classifies_workflows(survey: str) -> None:
    assert ".github/workflows/" in survey
    for purpose in ("runs the tests", "deploys", "releases"):
        assert purpose in survey


def test_survey_records_non_actions_ci_systems(survey: str) -> None:
    for marker in ("Jenkinsfile", ".gitlab-ci.yml", "bitbucket-pipelines.yml"):
        assert marker in survey


def test_profile_proposes_the_test_workflow_only(profile: str) -> None:
    assert "ci_workflow_file" in profile
    assert "never a deploy, release, or" in profile


def test_profile_names_the_merge_queue_conditions(profile: str) -> None:
    assert "merge_group" in profile
    assert "GitHub is bound" in profile


def test_binding_teaches_the_triggers_the_gate_needs(binding: str) -> None:
    assert "yoke_dispatch_id" in binding
    assert "workflow_dispatch" in binding
    assert "pull_request" in binding


def test_binding_names_the_merge_queue_declaration(binding: str) -> None:
    assert "--cap-type merge_queue" in binding
    assert "merge_group" in binding
