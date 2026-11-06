"""Conduct's shipped entry order must reach the claim activation gate."""

from pathlib import Path

from runtime.api.conftest import insert_item
from runtime.api.domain._path_claims_test_helpers import seed_claim, seed_target
from yoke_core.domain.path_claims_activation import activate
from yoke_core.domain.workflow_activation_status_gates import evaluate_claim_activation


def test_recipe_prepares_claim_before_transition(test_db):
    root = Path(__file__).resolve().parents[3]
    recipe = root / ".agents/skills/yoke/conduct/entry-activation-resolution.md"
    item_id = 7
    insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    claim_id = seed_claim(
        test_db,
        item_id=item_id,
        target_id=seed_target(test_db, path_string="src/"),
        state="planned",
    )
    gate_args = dict(
        item_id=item_id, target_status="implementing", db_path="", conn=test_db
    )
    assert evaluate_claim_activation(**gate_args) is not None
    prepared = transitioned = False
    for line in recipe.read_text().splitlines():
        if line.startswith("yoke worktree prepare "):
            # The preparation primitive takes the real claim's activation lock.
            activate(test_db, claim_id=claim_id, base_commit_sha="a" * 40)
            prepared = True
        elif line.startswith("yoke lifecycle transition "):
            assert prepared
            assert evaluate_claim_activation(**gate_args) is None
            transitioned = True
    assert transitioned
