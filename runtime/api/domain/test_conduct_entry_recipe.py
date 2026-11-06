"""Conduct's shipped entry order must reach the claim activation gate."""

from pathlib import Path

from yoke_core.domain import path_claims_gate
from yoke_core.domain.workflow_activation_status_gates import evaluate_claim_activation


def test_recipe_prepares_claim_before_transition(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    recipe = root / ".agents/skills/yoke/conduct/entry-activation-resolution.md"
    pending = [(3, "planned")]
    monkeypatch.setattr(path_claims_gate, "gate_state_for_item", lambda *_: pending)
    gate_args = dict(item_id=7, target_status="implementing", db_path="", conn=object())
    assert evaluate_claim_activation(**gate_args) is not None
    prepared = transitioned = False
    for line in recipe.read_text().splitlines():
        if line.startswith("yoke worktree prepare "):
            pending.clear()  # preparation's activation operation acquired the claim
            prepared = True
        elif line.startswith("yoke lifecycle transition "):
            assert prepared
            assert evaluate_claim_activation(**gate_args) is None
            transitioned = True
    assert transitioned
