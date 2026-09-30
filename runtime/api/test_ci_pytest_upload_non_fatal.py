"""The pytest-output upload reports; it does not decide the shard.

A green shard once concluded red because ``Upload pytest output`` failed with a
non-retryable 403 from the artifact intermediary. The job conclusion turned the
required check red, GitHub refused to enqueue, and the landing-stopped notice
sent the worker to fix a lane that had nothing wrong with it. Losing the
artifact must degrade diagnosis, never overturn the result being reported.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.yaml_helper import load_document

REPO_ROOT = Path(__file__).resolve().parents[2]
YOKE_CI = REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml"
UPLOAD_STEP = "Upload pytest output"
PYTEST_STEP = "Run pytest"


def _shard_steps() -> list[dict]:
    workflow = load_document(YOKE_CI)
    return workflow["jobs"]["test_shard"]["steps"]


def _step(name: str) -> dict:
    for step in _shard_steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"yoke-ci test_shard has no {name!r} step")


def test_pytest_output_upload_cannot_fail_the_shard() -> None:
    assert _step(UPLOAD_STEP)["continue-on-error"] is True


def test_pytest_itself_still_decides_the_shard() -> None:
    """The waiver covers the reporting step alone — a tolerated pytest step
    would report green while the suite failed."""
    assert "continue-on-error" not in _step(PYTEST_STEP)


def test_upload_still_runs_when_pytest_fails() -> None:
    """The artifact is most valuable on a red shard, so the step stays
    ``always()``; tolerating its failure must not stop it running."""
    assert _step(UPLOAD_STEP)["if"].startswith("always()")


def test_no_other_shard_step_tolerates_failure() -> None:
    tolerant = [
        step.get("name")
        for step in _shard_steps()
        if step.get("continue-on-error") is True
    ]
    assert tolerant == [UPLOAD_STEP]
