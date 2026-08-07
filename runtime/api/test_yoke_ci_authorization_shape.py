"""Regression coverage for yoke-ci authorization shape.

Keeps the runner-consuming aggregate tail gone and pins the branch-
protection expectation to CLA's signature-check rather than deleted
yoke-ci check names. Sibling of ``test_core_container.py`` so that file
stays under the authored-file line limit.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_hc_branch_protection import (
    EXPECTED_CHECKS,
    context_matches_job,
    orphan_required_contexts,
    workflow_job_names,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
YOKE_CI = WORKFLOWS / "yoke-ci.yml"


def test_yoke_ci_has_no_runner_consuming_aggregate_tail() -> None:
    workflow = YOKE_CI.read_text(encoding="utf-8")

    assert "needs: test_shard" not in workflow
    assert "SHARD_RESULT" not in workflow
    assert "\n  test:\n" not in workflow
    assert "name: test\n" not in workflow
    assert "test_shard:" in workflow
    assert "  container:" in workflow
    assert "reuse_coverage:" in workflow
    assert "needs: [reuse_coverage]" in workflow
    assert "REUSE_WINDOW_HOURS:" in workflow
    assert "yoke_core.tools.yoke_ci_tree_reuse" in workflow


def test_declared_required_contexts_match_workflow_jobs() -> None:
    job_names = workflow_job_names(WORKFLOWS)

    assert "signature-check" in job_names
    assert "test-shard" in job_names
    assert "container" in job_names
    for context in EXPECTED_CHECKS:
        assert context_matches_job(context, job_names), context
    assert orphan_required_contexts(EXPECTED_CHECKS, job_names) == ()


def test_orphan_detection_flags_deleted_aggregate_names() -> None:
    job_names = workflow_job_names(WORKFLOWS)
    stale = ("test (3.10)", "test (3.13)", "test-postgres")

    assert orphan_required_contexts(stale, job_names) == stale
    assert context_matches_job("test-shard (3.10, 1)", job_names)
