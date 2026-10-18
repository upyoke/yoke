"""Regression coverage for yoke-ci authorization shape.

Keeps the runner-consuming aggregate tail gone and pins the branch-
protection expectation to CLA's signature-check rather than deleted
yoke-ci check names. Sibling of ``test_core_container.py`` so that file
stays under the authored-file line limit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.yaml_helper import load_document
from yoke_core.tools import ci_shards
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
    assert context_matches_job("browser_runtime / browser-runtime", job_names)
    for context in EXPECTED_CHECKS:
        assert context_matches_job(context, job_names), context
    assert orphan_required_contexts(EXPECTED_CHECKS, job_names) == ()


@pytest.mark.parametrize(
    "fields",
    [
        "    name: named-check\n    timeout-minutes: 5\n",
        "    timeout-minutes: 5\n    name: named-check\n",
        "    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    name: named-check\n",
    ],
)
def test_workflow_job_names_ignore_field_order(tmp_path, fields) -> None:
    (tmp_path / "checks.yml").write_text(
        "name: workflow-name\njobs:\n  check_job:\n"
        + fields
        + "    env:\n      name: environment-name\n"
        "    steps:\n      - name: step-name\n        run: echo checked\n",
        encoding="utf-8",
    )

    names = workflow_job_names(tmp_path)

    assert names == ("named-check",)
    assert orphan_required_contexts(("named-check",), names) == ()


def test_reuse_coverage_runs_on_every_ci_event() -> None:
    assert "if" not in _yoke_ci()["jobs"]["reuse_coverage"]


def _required_contexts() -> tuple[str, ...]:
    declared = json.loads(MERGE_QUEUE.read_text(encoding="utf-8"))
    return tuple(
        str(entry["context"])
        for rule in declared["ruleset"]["rules"]
        if rule["type"] == "required_status_checks"
        for entry in rule["parameters"]["required_status_checks"]
    )


def _jobs_for_context(workflow: dict, context: str) -> list[dict]:
    caller_context = context.split(" / ", 1)[0]
    return [
        job
        for job_id, job in workflow["jobs"].items()
        if context_matches_job(caller_context, (str(job.get("name") or job_id),))
    ]


def test_every_required_context_reports_on_the_reuse_skip_path() -> None:
    """A skipped job reports skipped; an absent one leaves the check pending.

    The queue's required contexts are satisfied by jobs the reuse probe turns
    off. Removing a job from the graph — or gating one on an event filter the
    merge_group run never matches — would strand its context instead of
    concluding it.

    A matrix job is the exception that once stranded a queue entry for good. A
    skipped matrix job never evaluates its matrix, so it reports one check
    under the bare job name and none of the per-matrix contexts protection
    actually requires. Its reuse verdict therefore belongs on its steps, and
    :func:`test_a_matrix_job_carries_the_reuse_verdict_on_its_steps` is where
    that half is enforced.

    A reusable-workflow caller is the same trap under a different name. The
    required context is ``caller / inner-job``. Skipping the caller reports
    only the caller id and never the nested name, so the caller stays on the
    graph and the inner workflow no-ops.
    """
    workflows = (
        _yoke_ci(),
        load_document(WORKFLOWS / "yoke-build-artifacts.yml"),
    )
    contexts = _required_contexts()

    # Pinned as a set rather than a count: the shard half is whatever the
    # fan-out produces, so widening the shards moves this expectation with it
    # while dropping a context still fails.
    versions = ci_shards.python_versions()
    assert set(contexts) == {
        "repo-contracts",
        "reuse-coverage",
        "build",
        "attest-validated-release-provenance",
        "container",
        "browser_runtime / browser-runtime",
    } | {
        f"test-shard ({version}, {shard})"
        for version in versions
        for shard in ci_shards.shard_list()
    }
    for context in contexts:
        matched = [
            job
            for workflow in workflows
            for job in _jobs_for_context(workflow, context)
        ]
        assert matched, context
        for job in matched:
            condition = " ".join(str(job.get("if") or "").split())
            # An event filter is what would make the check absent rather than
            # skipped; the reuse verdict may gate only a non-matrix job.
            if "github.event_name" in condition:
                assert "github.event_name == 'merge_group'" in condition, context
                continue  # The signer runs on queue candidates, never ordinary PRs.
            if job.get("uses") or (
                "strategy" in job and "matrix" in job.get("strategy", {})
            ):
                assert "skip_suite" not in condition, context
            else:
                assert not condition or "skip_suite" in condition, context


def test_a_matrix_job_carries_the_reuse_verdict_on_its_steps() -> None:
    """Reuse still has to save the work it exists to save.

    Letting the matrix expand is only half the fix. The steps that ARE the
    cost — runner setup, interpreter and dependency installs, Postgres, and
    pytest — stay guarded by the verdict the job itself may no longer carry,
    so a covered tree spends only the job's own scheduling.
    """
    workflow = _yoke_ci()
    matrix_jobs = [
        job
        for context in _required_contexts()
        for job in _jobs_for_context(workflow, context)
        if "matrix" in job.get("strategy", {})
    ]

    assert matrix_jobs
    for job in matrix_jobs:
        assert job["env"]["SUITE_ALREADY_PROVEN"].endswith("skip_suite }}")
        for step in job["steps"]:
            assert "SUITE_ALREADY_PROVEN != 'true'" in str(step.get("if")), step["name"]


def test_every_ci_event_runs_both_interpreter_legs() -> None:
    """Pull requests carry the oldest leg so the queue can reuse their proof."""
    shard = _yoke_ci()["jobs"]["test_shard"]
    assert "github.event_name" not in json.dumps(shard)
    assert "RUN_PYTHON_LEG" not in YOKE_CI.read_text(encoding="utf-8")


def test_only_a_run_that_executes_the_suite_publishes_coverage_evidence() -> None:
    """A reusing run publishes nothing, so reuse never renews a proof's age."""
    job = _yoke_ci()["jobs"]["reuse_coverage"]
    steps = {step["name"]: step for step in job["steps"]}
    record = steps["Record the tree and coverage this run executes"]
    upload = steps["Publish coverage evidence"]
    for step in (record, upload):
        assert step["if"] == "steps.probe.outputs.skip_suite != 'true'"
    assert "yoke_core.tools.yoke_ci_coverage_evidence" in str(record["run"])
    assert upload["with"]["name"] == "${{ steps.evidence.outputs.artifact_name }}"
    assert upload["with"]["path"] == "yoke-ci-coverage.json"
    assert upload["with"]["overwrite"] is True
    assert int(upload["with"]["retention-days"]) * 24 >= int(
        _yoke_ci()["env"]["REUSE_WINDOW_HOURS"]
    )


def test_long_work_jobs_use_cancellation_aware_conditions() -> None:
    jobs = _yoke_ci()["jobs"]
    contracts_ok = "${{ !cancelled() && needs.repo_contracts.result == 'success' }}"
    assert " ".join(str(jobs["test_shard"]["if"]).split()) == contracts_ok
    assert " ".join(str(jobs["browser_runtime"]["if"]).split()) == contracts_ok
    # Python coverage never stands in for the commit-versioned image build.
    assert "if" not in jobs["container"] and "needs" not in jobs["container"]
    steps = {step["name"]: step for step in jobs["test_shard"]["steps"]}
    assert "always()" in str(steps["Upload pytest output"]["if"])
    assert "always()" in str(steps["Stop Postgres"]["if"])


def test_orphan_detection_flags_deleted_aggregate_names() -> None:
    job_names = workflow_job_names(WORKFLOWS)
    stale = ("test (3.10)", "test (3.13)", "test-postgres")

    assert orphan_required_contexts(stale, job_names) == stale
    assert context_matches_job("test-shard (3.10, 1)", job_names)
