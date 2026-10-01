"""Workflow check contexts follow YAML job structure, not text indentation."""

from yoke_core.engines.doctor_hc_branch_protection import (
    orphan_required_contexts,
    workflow_job_names,
)


def test_job_names_follow_other_fields_and_default_to_id(tmp_path):
    (tmp_path / "checks.yml").write_text(
        """name: workflow-name
jobs:
  named:
    timeout-minutes: 5
    runs-on: ubuntu-latest
    name: 'Build: release'
    steps:
      - name: nested-step
        run: echo ok
  unnamed:
    runs-on: ubuntu-latest
    steps: []
env:
  name: not-a-job
"""
    )
    names = workflow_job_names(tmp_path)
    assert names == ("Build: release", "unnamed")
    assert orphan_required_contexts(("named", "Build: release", "unnamed"), names) == (
        "named",
    )


def test_flow_mappings_and_duplicate_contexts(tmp_path):
    (tmp_path / "a.yml").write_text("jobs: {first: {name: check}, second: {}}\n")
    (tmp_path / "b.yml").write_text("jobs: {another: {name: check}}\n")
    (tmp_path / "empty.yml").write_text("# no jobs\n")
    assert workflow_job_names(tmp_path) == ("check", "second")
