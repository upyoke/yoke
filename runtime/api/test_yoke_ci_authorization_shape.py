"""Regression coverage for yoke-ci authorization shape.

Keeps the runner-consuming aggregate tail gone and pins the branch-
protection expectation to CLA's signature-check rather than deleted
yoke-ci check names. Sibling of ``test_core_container.py`` so that file
stays under the authored-file line limit.
"""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.yaml_helper import load_document
from yoke_core.engines.doctor_hc_branch_protection import (
    EXPECTED_CHECKS,
    context_matches_job,
    orphan_required_contexts,
    workflow_job_names,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
YOKE_CI = WORKFLOWS / "yoke-ci.yml"
MERGE_QUEUE = REPO_ROOT / ".yoke" / "merge-queue.json"


def _yoke_ci() -> dict:
    return load_document(YOKE_CI)


def test_yoke_ci_has_no_runner_consuming_aggregate_tail() -> None:
    workflow = YOKE_CI.read_text(encoding="utf-8")

    assert "needs: test_shard" not in workflow
    assert "SHARD_RESULT" not in workflow
    assert "\n  test:\n" not in workflow
    assert "name: test\n" not in workflow
    assert "repo_contracts:" in workflow
    assert "needs: [repo_contracts, reuse_coverage]" in workflow
    assert "test_shard:" in workflow
    assert "  container:" in workflow
    assert "reuse_coverage:" in workflow
    assert "REUSE_WINDOW_HOURS:" in workflow
    assert "yoke_core.tools.yoke_ci_tree_reuse" in workflow
    assert "yoke_core.tools.ci_repo_contracts" in workflow


def test_declared_required_contexts_match_workflow_jobs() -> None:
    job_names = workflow_job_names(WORKFLOWS)

    assert "signature-check" in job_names
    assert "repo-contracts" in job_names
    assert "reuse-coverage" in job_names
    assert "test-shard" in job_names
    assert "container" in job_names
    for context in EXPECTED_CHECKS:
        assert context_matches_job(context, job_names), context
    assert orphan_required_contexts(EXPECTED_CHECKS, job_names) == ()


def test_reuse_coverage_runs_on_merge_group_as_well_as_main_push() -> None:
    workflow = _yoke_ci()

    condition = " ".join(str(workflow["jobs"]["reuse_coverage"]["if"]).split())
    assert "github.event_name == 'merge_group'" in condition
    assert "github.ref == 'refs/heads/main'" in condition


def test_every_required_context_reports_on_the_reuse_skip_path() -> None:
    """A skipped job reports skipped; an absent one leaves the check pending.

    The queue's required contexts are satisfied by jobs the reuse probe
    turns off through a job-level condition. Removing a job from the graph —
    or gating one on an event filter the merge_group run never matches —
    would strand its context instead of concluding it.
    """
    workflow = _yoke_ci()
    declared = json.loads(MERGE_QUEUE.read_text(encoding="utf-8"))
    contexts = tuple(
        str(entry["context"])
        for rule in declared["ruleset"]["rules"]
        if rule["type"] == "required_status_checks"
        for entry in rule["parameters"]["required_status_checks"]
    )
    gating = {
        str(job.get("name") or job_id): " ".join(str(job.get("if") or "").split())
        for job_id, job in workflow["jobs"].items()
    }

    assert len(contexts) == 10
    for context in contexts:
        matched = [
            condition for name, condition in gating.items()
            if context_matches_job(context, (name,))
        ]
        assert matched, context
        # Gated only on the reuse verdict (or not at all) — never on an event
        # filter, which is what would make the check absent rather than skipped.
        assert all(
            not condition or "reuse_coverage.outputs.skip_suite" in condition
            for condition in matched
        ), context


def test_orphan_detection_flags_deleted_aggregate_names() -> None:
    job_names = workflow_job_names(WORKFLOWS)
    stale = ("test (3.10)", "test (3.13)", "test-postgres")

    assert orphan_required_contexts(stale, job_names) == stale
    assert context_matches_job("test-shard (3.10, 1)", job_names)
