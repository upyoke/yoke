"""Contracts for changed-path-gated browser-runtime CI coverage."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.yaml_helper import load_document


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
BROWSER_RUNTIME_WORKFLOW = WORKFLOWS / "browser-runtime-tests.yml"
YOKE_CI = WORKFLOWS / "yoke-ci.yml"


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def test_yoke_ci_calls_browser_runtime_gate_after_repo_contracts() -> None:
    workflow = load_document(YOKE_CI)
    job = workflow["jobs"]["browser_runtime"]

    assert job["uses"] == "./.github/workflows/browser-runtime-tests.yml"
    assert job["needs"] == ["repo_contracts", "reuse_coverage"]
    condition = " ".join(str(job["if"]).split())
    assert "needs.repo_contracts.result == 'success'" in condition
    assert "needs.reuse_coverage.outputs.skip_suite != 'true'" in condition


def test_browser_runtime_workflow_gates_every_expensive_step_on_its_tree() -> None:
    text = BROWSER_RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    assert "\non:\n  workflow_call:\n" in text
    workflow = load_document(BROWSER_RUNTIME_WORKFLOW)

    runtime_dir = workflow["env"]["BROWSER_RUNTIME_DIR"]
    assert runtime_dir.endswith("/browser_runtime")
    job = workflow["jobs"]["browser-runtime"]
    detect = _step(job, "Detect browser-runtime changes")["run"]
    assert 'git merge-base HEAD "$base_ref"' in detect
    assert 'git diff --quiet "$base_sha" HEAD -- "$BROWSER_RUNTIME_DIR"' in detect
    assert "should_run=false" in detect
    assert "should_run=true" in detect

    guarded = {
        step["name"]
        for step in job["steps"]
        if "steps.change_scope.outputs.should_run == 'true'"
        in str(step.get("if"))
    }
    assert guarded == {
        "Set up Node.js",
        "Install browser-runtime dependencies",
        "Install Chromium",
        "Run browser-runtime tests",
    }


def test_browser_runtime_workflow_provisions_and_runs_the_locked_suite() -> None:
    job = load_document(BROWSER_RUNTIME_WORKFLOW)["jobs"]["browser-runtime"]

    checkout = _step(job, "Checkout")
    assert checkout["with"]["fetch-depth"] == 0
    assert _step(job, "Install browser-runtime dependencies")["run"] == "npm ci"
    assert _step(job, "Install Chromium")["run"] == (
        "npx --no-install playwright install --with-deps chromium"
    )
    assert _step(job, "Run browser-runtime tests")["run"] == "npm test"
