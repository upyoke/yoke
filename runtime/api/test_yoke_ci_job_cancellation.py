"""Job-level CI conditions skip cancelled work without dropping eligible runs."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.yaml_helper import load_document

YOKE_CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "yoke-ci.yml"
WORK_JOBS = ("test_shard", "browser_runtime", "container")
STEP_ALWAYS = ("Upload pytest output", "Stop Postgres")


def _jobs() -> dict:
    return load_document(YOKE_CI)["jobs"]


def _expr(raw: object) -> str:
    text = " ".join(str(raw).split())
    if text.startswith("${{") and text.endswith("}}"):
        return text[3:-2].strip()
    return text


def _eval(expr: str, *, cancelled: bool, needs: dict[str, dict]) -> bool:
    token = _expr(expr)
    if cancelled and "!cancelled()" in token:
        return False
    if "needs.repo_contracts.result == 'success'" in token:
        if needs.get("repo_contracts", {}).get("result") != "success":
            return False
    if "needs.reuse_coverage.outputs.skip_suite != 'true'" in token:
        skip = needs.get("reuse_coverage", {}).get("outputs", {}).get("skip_suite", "")
        if skip == "true":
            return False
    return True


def test_long_work_jobs_skip_when_the_run_is_cancelled() -> None:
    jobs = _jobs()
    needs = {
        "repo_contracts": {"result": "success"},
        "reuse_coverage": {"result": "success", "outputs": {"skip_suite": ""}},
    }
    for name in WORK_JOBS:
        assert _eval(jobs[name]["if"], cancelled=True, needs=needs) is False


def test_long_work_jobs_skip_when_repo_contracts_failed() -> None:
    jobs = _jobs()
    needs = {
        "repo_contracts": {"result": "failure"},
        "reuse_coverage": {"result": "skipped", "outputs": {"skip_suite": ""}},
    }
    for name in ("test_shard", "browser_runtime"):
        assert _eval(jobs[name]["if"], cancelled=False, needs=needs) is False


def test_long_work_jobs_run_when_eligible_and_reuse_coverage_is_skipped() -> None:
    jobs = _jobs()
    needs = {
        "repo_contracts": {"result": "success"},
        "reuse_coverage": {"result": "skipped", "outputs": {"skip_suite": ""}},
    }
    for name in WORK_JOBS:
        assert _eval(jobs[name]["if"], cancelled=False, needs=needs) is True


def test_container_still_skips_when_coverage_is_already_proven() -> None:
    jobs = _jobs()
    needs = {
        "reuse_coverage": {"result": "success", "outputs": {"skip_suite": "true"}},
    }
    assert _eval(jobs["container"]["if"], cancelled=False, needs=needs) is False


def test_job_conditions_are_cancellation_aware_not_always() -> None:
    jobs = _jobs()
    for name in WORK_JOBS:
        condition = _expr(jobs[name]["if"])
        assert "!cancelled()" in condition
        assert "always()" not in condition


def test_step_cleanup_and_artifact_uploads_still_use_always() -> None:
    names = {step["name"]: step for step in _jobs()["test_shard"]["steps"]}
    for name in STEP_ALWAYS:
        assert "always()" in str(names[name]["if"])
        assert "!cancelled()" not in str(names[name]["if"])
