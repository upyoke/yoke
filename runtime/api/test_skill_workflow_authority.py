"""Shared delivery skills interpret immutable workflow authority."""

from pathlib import Path

from yoke_contracts.skill_registry import SKILLS_BY_ID

ROOT = Path(__file__).parents[2]
SKILLS = ROOT / ".agents" / "skills" / "yoke"


def test_skill_tree_uses_registered_lifecycle_transitions() -> None:
    retired = "advance"
    roots = (
        SKILLS,
        ROOT
        / "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke",
    )
    for root in roots:
        assert not (root / retired / "SKILL.md").exists()
        assert not list((root / retired).glob("*.md"))
    assert retired not in SKILLS_BY_ID


def test_retired_skip_phase_handlers_have_no_live_entrypoints() -> None:
    domain = ROOT / "packages/yoke-core/src/yoke_core/domain"
    engines = ROOT / "packages/yoke-core/src/yoke_core/engines"
    assert not list(domain.glob("advance_" + "skip*.py"))
    assert not (engines / ("doctor_hc_" + "skip_bypass.py")).exists()
    registry = (engines / "doctor_registry.py").read_text()
    assert "skip-polish-manual-hop" not in registry
    assert "advance-" + "skip" not in (domain / "event_catalog.py").read_text()
