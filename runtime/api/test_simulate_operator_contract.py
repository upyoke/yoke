"""Regression guards for the operator-facing simulation contract."""

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


def test_simulate_operator_classification_is_consistent():
    help_text = _read(SKILLS / "help" / "SKILL.md")
    for text in (help_text, _read(REPO / "docs" / "harness-bootstrap.md")):
        assert "/yoke simulate" in text
        assert "no terminal `yoke simulate` adapter" in text
    assert "/yoke simulate" in _read(SKILLS / "SKILL.md")
    assert "No `yoke simulate` command exists" in _read(
        SKILLS / "simulate" / "SKILL.md"
    )
    assert "plan, simulate" not in help_text


def test_epic_simulation_leaves_reflection_persistence_to_hook():
    role = " ".join(_read(REPO / "runtime" / "agents" / "simulator.md").split())
    assert "Reflection follows verdict/report; parent hook persists." in role
    assert "yoke ouroboros entry insert" not in _read(
        SKILLS / "simulate" / "epic-flow.md"
    )
