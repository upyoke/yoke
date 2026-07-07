"""Regression coverage for the codebase-reader naming doctrine."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
AGENTS = ROOT / "runtime" / "agents"
SKILLS = ROOT / ".agents" / "skills" / "yoke"

ASSUME_READER_PHRASE = "Assume future readers of the codebase will NOT have"
CURRENT_FUNCTION_PHRASE = "current function, purpose, mechanics"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_root_and_shared_prompt_doctrine_teach_codebase_reader_naming() -> None:
    agents_text = _read(ROOT / "AGENTS.md")
    assert "Codebase-reader naming" in agents_text
    assert ASSUME_READER_PHRASE in agents_text
    assert "Planning artifacts are scaffolding" in agents_text
    assert CURRENT_FUNCTION_PHRASE in agents_text

    prompt_text = _read(ROOT / "docs" / "prompt-philosophy.md")
    assert "future codebase readers" in prompt_text
    assert "ephemeral planning artifacts" in prompt_text
    assert "name live code/docs by current function" in prompt_text

    docs_text = _read(ROOT / "docs" / "agents.md")
    assert "codebase-reader complete" in docs_text
    assert "name every live surface by its current function" in docs_text


def test_canonical_authoring_agents_receive_naming_feedforward() -> None:
    for rel in (
        "product-manager.md",
        "product-designer.md",
        "architect.md",
        "engineer.md",
    ):
        text = _read(AGENTS / rel)
        assert "Codebase-reader naming" in text
        assert ASSUME_READER_PHRASE in text
        assert "planning artifacts" in text.lower()


def test_canonical_review_agents_gate_provenance_names() -> None:
    for rel in ("boss.md", "tester.md", "simulator.md"):
        text = _read(AGENTS / rel)
        assert "Codebase-reader naming" in text
        assert ASSUME_READER_PHRASE in text
        assert "provenance" in text


def test_core_skill_handoffs_carry_codebase_reader_rule() -> None:
    for path in (
        SKILLS / "idea" / "body-and-sync.md",
        SKILLS / "refine" / "review-rubric.md",
        SKILLS / "advance" / "implementing" / "implementation.md",
        SKILLS / "conduct" / "SKILL.md",
        SKILLS / "conduct" / "dispatch-context-prompts.md",
        SKILLS / "conduct" / "engineer-tester-dispatch.md",
        SKILLS / "polish" / "SKILL.md",
        SKILLS / "polish" / "review.md",
    ):
        text = _read(path)
        assert "codebase-reader" in text.lower(), f"{path} lost the doctrine"
        assert "planning artifact" in text.lower() or "task/spec/plan" in text.lower()


def test_rendered_adapters_inherit_canonical_reader_doctrine() -> None:
    for path in (
        ROOT / "runtime" / "harness" / "claude" / "agents" / "yoke-architect.md",
        ROOT / "runtime" / "harness" / "claude" / "agents" / "yoke-boss.md",
        ROOT / "runtime" / "harness" / "claude" / "agents" / "yoke-engineer.md",
        ROOT / "runtime" / "harness" / "claude" / "agents" / "yoke-product-designer.md",
        ROOT / "runtime" / "harness" / "claude" / "agents" / "yoke-product-manager.md",
        ROOT / "runtime" / "harness" / "claude" / "agents" / "yoke-simulator.md",
        ROOT / "runtime" / "harness" / "claude" / "agents" / "yoke-tester.md",
        ROOT / "runtime" / "harness" / "codex" / "agents" / "yoke-architect.toml",
        ROOT / "runtime" / "harness" / "codex" / "agents" / "yoke-boss.toml",
        ROOT / "runtime" / "harness" / "codex" / "agents" / "yoke-engineer.toml",
        ROOT / "runtime" / "harness" / "codex" / "agents" / "yoke-product-designer.toml",
        ROOT / "runtime" / "harness" / "codex" / "agents" / "yoke-product-manager.toml",
        ROOT / "runtime" / "harness" / "codex" / "agents" / "yoke-simulator.toml",
        ROOT / "runtime" / "harness" / "codex" / "agents" / "yoke-tester.toml",
    ):
        text = _read(path)
        assert "Codebase-reader naming" in text
        assert ASSUME_READER_PHRASE in text


def test_codebase_reader_rule_enumerates_full_provenance_token_set() -> None:
    """The master rule must explicitly name every purged provenance class, so a
    future agent cannot read it and think tiers, stages, slices, waves, field-notes,
    ticket/epic refs, or functional requirements are exempt."""
    agents_text = _read(ROOT / "AGENTS.md")
    marker = "Codebase-reader naming"
    assert marker in agents_text
    start = agents_text.index(marker)
    rule = agents_text[start:start + 2600]
    for term in (
        "tier", "stage", "slice", "track", "wave", "batch", "milestone",
        "field-note", "YOK-1234", "AC-7", "FR-3", "functional requirement",
        "acceptance criterion", "epic", "§7",
        # the rule must make clear it also governs FILE and DIRECTORY names
        "directory", "FILE and DIRECTORY",
    ):
        assert term in rule, f"codebase-reader rule must explicitly name '{term}'"


def test_engineer_body_enumerates_widened_provenance_language() -> None:
    text = _read(AGENTS / "engineer.md")
    for term in ("stage", "tier", "slice", "wave", "field-note", "YOK-N", "FR"):
        assert term in text, f"engineer body naming rule must name '{term}'"
