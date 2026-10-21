"""Timing evidence distinguishes queue, execution and concurrent case sums."""

import json

import pytest

from runtime.api.tools.ci_timing_report import report


@pytest.fixture
def evidence(tmp_path):
    directory = tmp_path / "pytest-output-3.14-1"
    directory.mkdir()
    (directory / "pytest-report.xml").write_text(
        '<testsuites><testsuite time="10" failures="0" errors="0">'
        '<testcase classname="example" name="passed" time="15"/>'
        '<testcase classname="example" name="skipped" time="2"><skipped/></testcase>'
        '</testsuite></testsuites>'
    )
    (directory / "pytest-output.txt").write_text(
        'CI runner capacity: {"cpu_count": 4}\n'
    )
    run = {
        "status": "completed", "conclusion": "success", "id": 1,
        "html_url": "https://example.test/run", "head_sha": "a" * 40,
        "created_at": "2026-01-01T00:00:00Z",
    }
    job = {
        "name": "test-shard", "conclusion": "success", "status": "completed",
        "created_at": "2026-01-01T00:00:02Z", "started_at": "2026-01-01T00:00:05Z",
        "completed_at": "2026-01-01T00:00:30Z", "labels": ["ubuntu-latest"],
        "steps": [{"name": "Run pytest", "started_at": "2026-01-01T00:00:15Z",
                   "completed_at": "2026-01-01T00:00:25Z"}],
    }
    coverage = {"run_id": 1, "commit": "b" * 40, "tree": "c" * 40,
                "coverage": {"python": {"3.14": "all"}, "shards": 1}}
    return run, {"jobs": [job], "total_count": 1}, coverage, tmp_path


def test_metrics_keep_execution_and_concurrent_case_time_separate(evidence):
    run, jobs, coverage, root = evidence
    result = report(root, run, jobs, coverage, root)
    assert result["workflow_seconds"] == 30
    assert result["jobs"][0]["queue_seconds"] == 3
    assert result["jobs"][0]["setup_seconds"] == 10
    assert result["jobs"][0]["test_seconds"] == 10
    assert result["runner_minutes"] == 25 / 60
    assert result["rounded_runner_minutes_estimate"] == 1
    assert result["tested_commit"] != result["head_commit"]
    endpoint = result["endpoints"]["3.14"]
    assert (endpoint["cases"], endpoint["passed"], endpoint["skipped"]) == (2, 1, 1)
    assert endpoint["aggregate_case_seconds"] == 17
    assert endpoint["suite_wall_seconds"] == [10]
    assert endpoint["runner_capacity"] == [{"cpu_count": 4}]
    json.dumps(result)


@pytest.mark.parametrize("defect", ["active", "wrong-run", "missing-job-page", "missing-shard", "duplicate"])
def test_incomplete_or_unrelated_evidence_refuses(evidence, defect):
    run, jobs, coverage, root = evidence
    if defect == "active":
        run["status"] = "in_progress"
    elif defect == "wrong-run":
        coverage["run_id"] = 2
    elif defect == "missing-job-page":
        jobs["total_count"] = 2
    else:
        coverage["coverage"]["shards"] = 2
        if defect == "duplicate":
            import shutil

            shutil.copytree(root / "pytest-output-3.14-1", root / "pytest-output-3.14-2")
    with pytest.raises((ValueError, OSError)):
        report(root, run, jobs, coverage, root)
