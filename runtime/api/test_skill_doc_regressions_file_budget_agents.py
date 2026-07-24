"""Agent and docs regressions for the File Budget contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    AGENTS,
    REPO,
    SKILLS,
    _read,
    _read_bundle,
)


class TestFileBudgetEngineerSubmission:
    """Engineer agent carries the file_budget: PASS|SKIP submission line."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "engineer": AGENTS / "yoke-engineer.md",
            "engineer_canonical": REPO / "runtime" / "agents" / "engineer.md",
        }

    def test_engineer_submission_block_has_file_budget_line(self, docs):
        text = _read(docs["engineer"])
        assert "file_budget: PASS | SKIP" in text

    def test_engineer_canonical_source_has_file_budget_line(self, docs):
        text = _read(docs["engineer_canonical"])
        assert "file_budget: PASS | SKIP" in text

    def test_engineer_explains_pass_and_skip_semantics(self, docs):
        text = _read(docs["engineer"])
        assert "PASS" in text and "350" in text
        assert "SKIP" in text


class TestFileBudgetTesterBackup:
    """Tester guidance positions file_line_check as backup verification."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "tester": AGENTS / "yoke-tester.md",
        }

    def test_tester_calls_file_line_check_a_backup(self, docs):
        text = _read(docs["tester"])
        assert "backup" in text.lower()
        assert "350" in text
        assert "file_line_check" in text

    def test_tester_warns_on_files_close_to_cap(self, docs):
        text = _read(docs["tester"])
        assert "300" in text


class TestFileBudgetCommandsDoc:
    """`.yoke/docs/commands.md` carries the File Budget cross-reference."""

    @pytest.fixture
    def commands_md(self) -> Path:
        return REPO / ".yoke" / "docs" / "commands.md"

    def test_commands_md_mentions_file_budget(self, commands_md):
        text = _read(commands_md)
        assert "File Budget" in text
        assert "350" in text
        assert "file_line_check" in text


class TestFileBudgetPreservesLateStageProse:
    """AC-13: existing late-stage 350-line prose stays in listed files."""

    @pytest.fixture
    def files(self) -> list[Path]:
        return [
            REPO / "runtime" / "agents" / "engineer.md",
            REPO / "runtime" / "agents" / "tester.md",
            REPO / "runtime" / "agents" / "architect" / "hard-constraints.md",
            SKILLS / "polish" / "review.md",
            REPO / ".yoke" / "docs" / "commands.md",
        ]

    def test_each_file_still_mentions_350(self, files):
        for path in files:
            text = _read(path)
            assert "350" in text, f"{path} dropped its 350-line mention"

    def test_each_file_still_invokes_file_line_check(self, files):
        for path in files:
            text = _read(path)
            assert "file_line_check" in text, f"{path} dropped file_line_check"


class TestFileBudgetRenderedAdaptersInSync:
    """AC-15: source agent files render cleanly to harness adapters."""

    def test_rendered_engineer_carries_file_budget_line(self):
        text = _read(REPO / "runtime" / "harness" / "claude" / "agents" / "yoke-engineer.md")
        assert "file_budget: PASS | SKIP" in text

    def test_rendered_tester_carries_backup_language(self):
        text = _read(REPO / "runtime" / "harness" / "claude" / "agents" / "yoke-tester.md")
        assert "backup" in text.lower()
        assert "file_line_check" in text

    def test_rendered_architect_carries_file_budget_constraint(self):
        text = _read(REPO / "runtime" / "harness" / "claude" / "agents" / "yoke-architect.md")
        assert "File Budget" in text


class TestFileBudgetCanonicalCheckerByteIdentical:
    """AC-16: the canonical ``file_line_check`` module still exists."""

    def test_canonical_checker_module_exists(self):
        from yoke_core.domain import file_line_check

        path = Path(file_line_check.__file__).resolve()
        assert path.is_file(), f"canonical checker missing: {path}"


class TestFileBudgetUpstreamPropagationBundle:
    """The full upstream chain references the File Budget."""

    def test_full_chain_mentions_file_budget(self):
        chain = [
            SKILLS / "idea" / "SKILL.md",
            SKILLS / "idea" / "body-and-sync.md",
            SKILLS / "refine" / "SKILL.md",
            SKILLS / "refine" / "review-rubric.md",
            SKILLS / "refine" / "update-protocol.md",
            SKILLS / "advance" / "implementing" / "implementation.md",
            SKILLS / "conduct" / "engineer-tester-dispatch.md",
            SKILLS / "conduct" / "dispatch-context-gates.md",
            REPO / "runtime" / "agents" / "architect.md",
            REPO / "runtime" / "agents" / "architect" / "hard-constraints.md",
            REPO / "runtime" / "agents" / "engineer.md",
            REPO / "runtime" / "agents" / "tester.md",
            REPO / ".yoke" / "docs" / "commands.md",
        ]
        bundle = _read_bundle(*chain)
        for path in chain:
            text = _read(path)
            assert "File Budget" in text or "file_budget" in text, (
                f"{path} is part of the File Budget chain but does not mention it"
            )
        assert "file_line_check" in bundle
