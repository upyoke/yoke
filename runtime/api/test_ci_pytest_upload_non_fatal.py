"""The pytest-output upload reports; it does not decide the shard.

A green shard once concluded red because ``Upload pytest output`` failed with a
non-retryable 403 from the artifact intermediary. The job conclusion turned the
required check red, GitHub refused to enqueue, and the landing-stopped notice
sent the worker to fix a lane that had nothing wrong with it. Losing the
artifact must degrade diagnosis, never overturn the result being reported.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.yaml_helper import load_document

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
UPLOAD_STEP = "Upload pytest output"
PYTEST_STEP = "Run pytest"


@pytest.fixture(
    params=[
        pytest.param(("yoke-ci.yml", "test_shard"), id="yoke-ci"),
        pytest.param(("yoke-suite.yml", "suite"), id="yoke-suite"),
    ]
)
def shard_steps(request: pytest.FixtureRequest) -> list[dict]:
    filename, job = request.param
    return load_document(WORKFLOWS / filename)["jobs"][job]["steps"]


def _step(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"Shard has no {name!r} step")


def test_pytest_output_upload_cannot_fail_the_shard(shard_steps: list[dict]) -> None:
    assert _step(shard_steps, UPLOAD_STEP)["continue-on-error"] is True


def test_pytest_itself_still_decides_the_shard(shard_steps: list[dict]) -> None:
    """The waiver covers the reporting step alone — a tolerated pytest step
    would report green while the suite failed."""
    assert "continue-on-error" not in _step(shard_steps, PYTEST_STEP)


def test_upload_still_runs_when_pytest_fails(shard_steps: list[dict]) -> None:
    """The artifact is most valuable on a red shard, so the step stays
    ``always()``; tolerating its failure must not stop it running."""
    assert _step(shard_steps, UPLOAD_STEP)["if"].startswith("always()")


def test_no_other_shard_step_tolerates_failure(shard_steps: list[dict]) -> None:
    tolerant = [
        step.get("name")
        for step in shard_steps
        if "continue-on-error" in step
    ]
    assert tolerant == [UPLOAD_STEP]


def test_yoke_suite_plan_steps_do_not_tolerate_failure() -> None:
    steps = load_document(WORKFLOWS / "yoke-suite.yml")["jobs"]["plan"]["steps"]
    assert all("continue-on-error" not in step for step in steps)
