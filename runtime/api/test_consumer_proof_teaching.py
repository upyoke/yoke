"""Intake and work instructions place consumer proof at release, not item merge."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative",
    [
        "docs/public/agents/rules/code-and-cli.md",
        "runtime/agents/product-manager.md",
        "runtime/agents/architect/task-templates.md",
        ".agents/skills/yoke/idea/infer-and-create.md",
        ".agents/skills/yoke/idea/delivery-requirements.md",
        ".agents/skills/yoke/conduct/dispatch-context-verify.md",
        "docs/public/verification/consumer-proof.md",
    ],
)
def test_ac_and_worker_contexts_use_release_time_consumer_proof(relative):
    text = (ROOT / relative).read_text()
    assert "release-time exact-pair gate" in text
    assert (
        "Require evidence the real consumer built against the exact pushed candidate"
        not in text
    )
    assert "a changed contract requires its consumer companion and evidence" not in text


def test_merge_routes_have_no_consumer_dispatch_hook():
    for relative in (
        "packages/yoke-core/src/yoke_core/engines/merge_worktree_execute.py",
        "packages/yoke-core/src/yoke_core/domain/merge_queue_route.py",
    ):
        assert "require_consumer_proof" not in (ROOT / relative).read_text()
