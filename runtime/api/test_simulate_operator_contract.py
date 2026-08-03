"""Regression guards for the operator-facing simulation contract."""

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


def test_simulate_operator_classification_is_consistent():
    surfaces = (
        _read(SKILLS / "SKILL.md"),
        _read(SKILLS / "help" / "SKILL.md"),
        _read(REPO / "docs" / "harness-bootstrap.md"),
    )
    for text in surfaces:
        assert "/yoke simulate" in text
        assert "no terminal `yoke simulate` adapter" in text

    assert "plan, simulate" not in surfaces[1]


def test_epic_simulation_leaves_reflection_persistence_to_hook():
    text = _read(SKILLS / "simulate" / "epic-flow.md")
    assert "PostToolUse Agent hook" in text
    assert "yoke ouroboros entry insert" not in text
