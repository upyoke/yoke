"""Whether a declared workflow is one the verification gate can reach."""

from __future__ import annotations

import pytest

from yoke_core.domain.github_actions_workflow_inspection import (
    declares_dispatch_correlation_input,
    declares_merge_group,
    inspect_declared_workflow,
    is_actions_workflow,
    other_ci_systems_present,
    resolve_ci_workflow_binding,
    workflow_triggers,
)


REACHABLE = """
on:
  pull_request:
    branches: [main]
  merge_group:
  workflow_dispatch:
    inputs:
      yoke_dispatch_id:
        required: false
        default: ""
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: make test
"""

DEPLOY_ON_TAGS = """
on:
  push:
    tags:
      - "v*"
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh
"""

DISPATCH_WITHOUT_CORRELATION = """
on:
  workflow_dispatch:
    inputs:
      target_environment:
        required: true
jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - run: ./promote.sh
"""

DISPATCH_ONLY = """
on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      yoke_dispatch_id:
        required: false
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: make test
"""


def _write_workflow(root, name: str, text: str):
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")
    return root


def test_unquoted_on_key_is_read_as_the_trigger_mapping(tmp_path):
    """PyYAML loads a bare ``on:`` as boolean True; triggers still resolve."""
    assert workflow_triggers(REACHABLE) == {
        "pull_request", "merge_group", "workflow_dispatch",
    }
    assert declares_merge_group(REACHABLE)
    assert declares_dispatch_correlation_input(REACHABLE)


def test_trigger_forms_other_than_a_mapping_are_read():
    assert workflow_triggers("on: merge_group\njobs:\n  a:\n    steps: []\n") == {
        "merge_group",
    }
    assert workflow_triggers("on: [push, merge_group]\njobs: {}\n") == {
        "push", "merge_group",
    }


def test_unparseable_or_non_workflow_yaml_declares_nothing():
    assert workflow_triggers("::: not yaml :::") == frozenset()
    assert not is_actions_workflow("just: a mapping\n")
    assert not is_actions_workflow(REACHABLE.replace("jobs:", "steps:"))


def test_reachable_workflow_verifies(tmp_path):
    _write_workflow(tmp_path, "ci.yml", REACHABLE)
    result = inspect_declared_workflow("ci.yml", checkout=tmp_path)
    assert result.verified
    assert result.reason_code == "reachable"
    assert result.declares_merge_group


def test_absent_workflow_refuses_and_names_the_repository(tmp_path):
    result = inspect_declared_workflow("ci.yml", checkout=tmp_path)
    assert not result.verified
    assert result.reason_code == "workflow_absent_from_repo"
    assert str(tmp_path) in result.message


def test_absent_workflow_names_the_other_ci_system_the_repo_runs(tmp_path):
    (tmp_path / "Jenkinsfile").write_text("pipeline {}", encoding="utf-8")
    result = inspect_declared_workflow("ci.yml", checkout=tmp_path)
    assert "Jenkins" in result.message
    assert "local `command` runner" in result.message


def test_other_ci_systems_are_reported_by_name(tmp_path):
    (tmp_path / ".gitlab-ci.yml").write_text("stages: []", encoding="utf-8")
    (tmp_path / "fastlane").mkdir()
    (tmp_path / "fastlane" / "Fastfile").write_text("lane :beta", encoding="utf-8")
    assert other_ci_systems_present(tmp_path) == ["GitLab CI", "fastlane"]
    assert other_ci_systems_present(None) == []


def test_a_deploy_workflow_on_tags_is_not_dispatchable(tmp_path):
    _write_workflow(tmp_path, "release.yml", DEPLOY_ON_TAGS)
    result = inspect_declared_workflow("release.yml", checkout=tmp_path)
    assert result.reason_code == "dispatch_input_missing"


def test_dispatch_without_the_correlation_input_refuses(tmp_path):
    _write_workflow(tmp_path, "promote.yml", DISPATCH_WITHOUT_CORRELATION)
    result = inspect_declared_workflow("promote.yml", checkout=tmp_path)
    assert result.reason_code == "dispatch_input_missing"
    assert "yoke_dispatch_id" in result.message


def test_no_checkout_here_reports_rather_than_deciding():
    result = inspect_declared_workflow("ci.yml", checkout=None)
    assert not result.verified
    assert result.reason_code == "checkout_unmapped"
    assert "yoke project register" in result.message


def test_dispatch_only_workflow_binds_but_names_the_second_suite(tmp_path):
    _write_workflow(tmp_path, "ci.yml", DISPATCH_ONLY)
    result = inspect_declared_workflow("ci.yml", checkout=tmp_path)
    assert result.verified
    assert result.reason_code == "pull_request_missing"
    bound, _ = resolve_ci_workflow_binding(
        "ci.yml", checkout=tmp_path, project="p", scope="quick",
    )
    assert bound == "ci.yml"


def test_a_queued_project_cannot_bind_a_workflow_without_pull_request(tmp_path):
    _write_workflow(tmp_path, "ci.yml", DISPATCH_ONLY)
    with pytest.raises(ValueError) as excinfo:
        resolve_ci_workflow_binding(
            "ci.yml",
            checkout=tmp_path,
            project="p",
            scope="quick",
            lands_through_merge_queue=True,
        )
    assert "pull_request" in str(excinfo.value)


def test_a_caller_without_an_operator_binds_local_instead_of_refusing(tmp_path):
    bound, inspection = resolve_ci_workflow_binding(
        "ci.yml",
        checkout=tmp_path,
        project="p",
        scope="quick",
        refuse_unreachable=False,
    )
    assert bound == ""
    assert inspection.reason_code == "workflow_absent_from_repo"


def test_an_unreadable_declaration_is_neither_bound_nor_refused(tmp_path):
    bound, inspection = resolve_ci_workflow_binding(
        "ci.yml", checkout=None, project="p", scope="quick",
    )
    assert bound == "ci.yml"
    assert inspection.reason_code == "checkout_unmapped"
