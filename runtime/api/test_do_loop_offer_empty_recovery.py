"""Do-loop recipe: empty offer stdout is not a no-work answer."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DO = REPO_ROOT / ".agents" / "skills" / "yoke" / "do"
PACKAGED_DO = (
    REPO_ROOT
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "install_bundle_tree"
    / ".agents"
    / "skills"
    / "yoke"
    / "do"
)


@pytest.mark.parametrize("root", (SOURCE_DO, PACKAGED_DO))
def test_empty_offer_stdout_reads_durable_events_before_no_work(root: Path) -> None:
    loop = (root / "loop.md").read_text(encoding="utf-8")
    followups = (root / "loop-followups.md").read_text(encoding="utf-8")
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    loop_flat = " ".join(loop.split())

    assert "empty stdout" in loop
    assert "do **not** treat that as no-work" in loop_flat
    assert (
        "yoke events query --event-name HarnessSessionOffered --session {SESSION_ID}"
        in loop
    )
    assert (
        "yoke events query --event-name FrontierStepSelected --session {SESSION_ID}"
        in loop
    )
    assert "yoke events query --event-name WorkClaimed --session {SESSION_ID}" in loop
    assert (
        "yoke events query --event-name NextActionChosen --session {SESSION_ID}"
        in loop
    )
    assert "Do not release the claim this offer already took" in loop_flat
    assert "print the raw output and stop" not in followups
    assert "do not call Step D yet" in followups
    assert "HarnessSessionOffered" in followups
    assert "not a no-work answer" in skill
    assert "FrontierStepSelected" in skill
    assert "WorkClaimed" in skill
