"""The release bridge never runs beside, or outlives, another for one environment."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "platform-release-bridge.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> dict:
    (job,) = _workflow()["jobs"].values()
    return {step["name"]: step for step in job["steps"]}


def test_one_bridge_per_environment_runs_at_a_time() -> None:
    concurrency = _workflow()["concurrency"]

    assert concurrency["group"] == (
        "platform-release-bridge-${{ inputs.target_environment }}"
    )
    # The owning deployment run cancels its bridge; a newer bridge only waits.
    assert concurrency["cancel-in-progress"] is False


def test_the_promotion_step_records_every_run_it_dispatches() -> None:
    run = _steps()["Dispatch and await Platform pin promotion and release"]["run"]

    assert '--started-runs-file "$RUNNER_TEMP/platform-promotion-runs.txt"' in run


def test_a_cancelled_or_failing_bridge_cancels_the_promotion_it_started() -> None:
    steps = _steps()
    names = list(steps)
    cleanup = steps["Cancel the Platform promotion this bridge started"]

    assert names[-1] == "Cancel the Platform promotion this bridge started"
    assert cleanup["if"] == "cancelled() || failure()"
    assert cleanup["env"]["STARTED_RUNS"] == (
        "${{ runner.temp }}/platform-promotion-runs.txt"
    )
    script = cleanup["run"]
    assert "YOKE_PLATFORM_RELEASE_API_TOKEN" in script
    assert 'yoke github-actions run cancel upyoke/platform "$run_id"' in script
    assert "--project platform" in script
    assert "platform_promotion_not_cancelled" in script
