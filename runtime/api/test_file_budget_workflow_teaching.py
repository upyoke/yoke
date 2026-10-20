"""Focused teaching checks for the independent File Budget policy axis."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills" / "yoke"
UI = ROOT / "packages" / "yoke-core" / "src" / "yoke_core" / "ui" / "static"


def _read(path: Path) -> str:
    """Read one file, or a whole command directory as its entrypoint + phases."""
    if path.is_dir():
        entry = path / "SKILL.md"
        phases = sorted(p for p in path.glob("*.md") if p.name != "SKILL.md")
        return "\n".join(p.read_text(encoding="utf-8") for p in (entry, *phases))
    return path.read_text(encoding="utf-8")


def _bundle(*paths: Path) -> str:
    return "\n".join(_read(path) for path in paths)


def _command(skill: str) -> Path:
    """Marker for a whole command; _read expands a directory to its corpus."""
    return SKILLS / skill


def test_workflow_skills_resolve_file_budget_and_claims_independently() -> None:
    paths = [
        ROOT / "AGENTS.md",
        _command("idea"),
        _command("refine"),
        ROOT / ".yoke/docs/agents/rules/lanes-and-claims.md",
    ]
    for path in paths:
        text = _read(path)
        assert "File Budget" in text
        assert "path claim" in text.lower() or "path-claim" in text.lower()
    assert "independent" in _bundle(*paths).lower()


def test_skills_consume_central_effective_policy_projection() -> None:
    text = _read(ROOT / ".yoke/docs/agents/rules/lanes-and-claims.md")
    assert "workflows.item.get" in text
    assert "effective_policies" in text
    for path in (
        SKILLS / "refine" / "workflow-context.md",
        SKILLS / "implement" / "entry.md",
        _command("conduct"),
        _command("dash"),
    ):
        assert "yoke workflows item get" in _read(path)

    contexts = _bundle(
        SKILLS / "refine" / "workflow-context.md",
        SKILLS / "implement" / "entry.md",
    )
    assert 'policies["file_budget"]' not in contexts
    assert "ITEM_WORKFLOW_POSTURE_JSON" not in contexts
    assert "_workflow_posture_json" not in contexts


def test_teaching_covers_all_axis_combinations_and_universal_cap() -> None:
    text = _bundle(
        ROOT / "AGENTS.md",
        ROOT / ".yoke/docs/agents/rules/lanes-and-claims.md",
        _command("idea"),
        _command("refine"),
        _command("dash"),
        _command("blitz"),
    ).lower()
    assert "both off" in text
    assert "budget off" in text and "claims on" in text
    assert "budget on" in text and "claims off" in text
    assert "both effective axes are enabled" in text
    assert "350-line" in text
    assert "file_line_check" in text


def test_each_planning_home_teaches_the_both_off_composition() -> None:
    for path in (
        ROOT / ".yoke/docs/agents/rules/lanes-and-claims.md",
        ROOT / "runtime" / "agents" / "architect" / "hard-constraints.md",
    ):
        assert "both off" in _read(path).lower()


def test_optional_budget_teaching_does_not_require_parent_section() -> None:
    idea = _read(SKILLS / "idea" / "body-and-sync.md")
    engineer = _read(ROOT / "runtime" / "agents" / "engineer.md")
    assert "[File Budget](file-budget.md) when enabled" in idea
    assert "disabled: dispatched scope applies without inventing a budget" in engineer
    assert "File Budget is mandatory for any implementation-bearing intake" not in idea


def test_item_ui_uses_central_effective_policies() -> None:
    facts = _read(UI / "item_view_facts.js")
    blitz = _read(UI / "universe_views_blitz.js")
    assert "workflow?.effective_policies?.file_budget" in facts
    assert "workflow?.effective_policies?.path_claims" in facts
    assert "workflow.effective_policies" in facts
    assert "workflow.effective_policies" in blitz
    assert "workflow?.policies?.file_budget" not in facts
    assert "workflow?.policies?.path_claims" not in facts
    assert "policies.file_budget" not in blitz
    assert "policies.path_claims" not in blitz
