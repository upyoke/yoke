"""Focused teaching checks for the independent File Budget policy axis."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents" / "skills" / "yoke"
UI = ROOT / "packages" / "yoke-core" / "src" / "yoke_core" / "ui" / "static"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bundle(*paths: Path) -> str:
    return "\n".join(_read(path) for path in paths)


def test_workflow_skills_resolve_file_budget_and_claims_independently() -> None:
    paths = [
        ROOT / "AGENTS.md",
        SKILLS / "idea" / "SKILL.md",
        SKILLS / "refine" / "SKILL.md",
        SKILLS / "advance" / "preflight-checks.md",
        SKILLS / "conduct" / "SKILL.md",
        SKILLS / "dash" / "SKILL.md",
        SKILLS / "blitz" / "SKILL.md",
    ]
    for path in paths:
        text = _read(path)
        assert "File Budget" in text
        assert "path claim" in text.lower() or "path-claim" in text.lower()
    text = _bundle(*paths).lower()
    assert "independent" in text
    assert "optional" in text
    assert "posture" in text


def test_skills_consume_central_effective_policy_projection() -> None:
    paths = [
        SKILLS / "idea" / "SKILL.md",
        SKILLS / "refine" / "workflow-context.md",
        SKILLS / "advance" / "workflow-context.md",
        SKILLS / "conduct" / "SKILL.md",
        SKILLS / "dash" / "SKILL.md",
        SKILLS / "blitz" / "SKILL.md",
    ]
    for path in paths:
        text = _read(path)
        assert "workflows.item.get" in text
        assert "effective_policies" in text

    contexts = _bundle(
        SKILLS / "refine" / "workflow-context.md",
        SKILLS / "advance" / "workflow-context.md",
    )
    assert 'policies["file_budget"]' not in contexts
    assert "ITEM_WORKFLOW_POSTURE_JSON" not in contexts
    assert "_workflow_posture_json" not in contexts


def test_teaching_covers_all_axis_combinations_and_universal_cap() -> None:
    text = _bundle(
        ROOT / "AGENTS.md",
        SKILLS / "idea" / "SKILL.md",
        SKILLS / "refine" / "SKILL.md",
        SKILLS / "dash" / "SKILL.md",
        SKILLS / "blitz" / "SKILL.md",
    ).lower()
    assert "both off" in text
    assert "budget off" in text and "claims on" in text
    assert "budget on" in text and "claims off" in text
    assert "both axes are enabled" in text
    assert "350-line" in text
    assert "file_line_check" in text


def test_each_execution_surface_teaches_the_both_off_composition() -> None:
    paths = [
        SKILLS / "advance" / "preflight-checks.md",
        SKILLS / "conduct" / "SKILL.md",
        SKILLS / "dash" / "SKILL.md",
        ROOT / "runtime" / "agents" / "architect.md",
    ]
    for path in paths:
        text = _read(path).lower()
        assert "both off" in text or "both are off" in text


def test_optional_budget_teaching_does_not_require_parent_section() -> None:
    idea = _read(SKILLS / "idea" / "body-and-sync.md")
    engineer = _read(ROOT / "runtime" / "agents" / "engineer.md")
    assert "When File Budget is off, omit that section." in idea
    assert "when disabled, use the dispatched execution scope" in engineer
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
