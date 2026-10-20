"""Onboard's guidance review moves work-scoped rules into execution instructions."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STRATEGY_STEP = (
    REPO_ROOT / ".agents" / "skills" / "yoke" / "onboard" / "strategy-conversation.md"
)
PUBLIC_ONBOARD = REPO_ROOT / "docs" / "public" / "projects" / "index.md"


def _strategy_step() -> str:
    return " ".join(STRATEGY_STEP.read_text(encoding="utf-8").split())


def test_guidance_review_moves_only_approved_work_scoped_rules():
    text = _strategy_step()
    assert "move work-specific `AGENTS.md` rules into execution instructions" in text
    assert "Per approved rule:" in text
    assert "delete the moved text from its source" in text


def test_guidance_review_sits_before_the_decision_walk():
    text = _strategy_step()
    review = text.index("move work-specific `AGENTS.md` rules")
    assert text.index("Seed, then read") < review
    assert review < text.index("Ask decisions one at a time")


def test_guidance_steps_create_then_scope_then_resolve():
    text = _strategy_step()
    order = text[text.index("Per approved rule:") :]
    assert order.index("create") < order.index("`set-scope`") < order.index("resolve")
    assert "unscoped reaches no work" in order


def test_public_onboarding_page_names_the_guidance_review():
    text = PUBLIC_ONBOARD.read_text(encoding="utf-8")
    assert "reviews the project's own rules" in text
    assert (
        "only\napproved ones are created; every-turn rules stay where they are" in text
    )
