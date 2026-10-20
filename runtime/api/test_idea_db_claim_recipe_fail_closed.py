"""Idea DB-claim recipe must fail closed when the spec read fails."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


def test_idea_db_claim_recipe_checks_spec_read_before_detector() -> None:
    text = _read(SKILLS / "idea" / "db-claim-classification.md")
    assert "a failed read stops here" in text
    assert 'yoke items get "PREFIX-{N}" spec | yoke db-claim prose-check' not in text
    assert text.index('yoke items get "$ITEM_REF" spec') < text.index(
        "yoke db-claim prose-check --stdin"
    )
