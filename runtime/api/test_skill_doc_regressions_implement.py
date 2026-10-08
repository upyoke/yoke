"""Implementation entry and canonical skill discovery contracts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _read,
    _read_skill_corpus,
)


# ---------------------------------------------------------------------------
# TestAdvanceFinalizeSkill
# ---------------------------------------------------------------------------


class TestImplementEntrySkill:
    """Implement entry must derive implementation entry from the exact pin."""

    @pytest.fixture
    def entry_doc(self) -> Path:
        doc = SKILLS / "implement" / "entry.md"
        assert doc.is_file()
        return doc

    def _entry_section(self, entry_doc: Path) -> str:
        text = _read(entry_doc)
        section = re.search(
            r"## Reach the binding's entry stage first.*?(?=^## Enter at)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        assert section is not None, (
            "implement/entry.md missing the implementation-entry source section"
        )
        return section.group(0)

    def test_implementation_entry_requires_pinned_implement_source(
        self, entry_doc: Path
    ):
        section_text = self._entry_section(entry_doc)
        # The engine dispatches one adjacent transition from the pinned
        # implement binding source.
        assert "advance_hop" not in section_text
        assert "from_stage_id" in section_text
        assert "single_implementation_lane" in section_text
        assert "pinned definition" in section_text
        # Raw intermediate status writes stay claim-protected.
        assert "ClaimVerificationDenied" in section_text

    def test_implementation_entry_drops_raw_intermediate_examples(
        self, entry_doc: Path
    ):
        section_text = self._entry_section(entry_doc)
        assert "items update {N} status refining-idea" not in section_text
        assert "items update {N} status refined-idea" not in section_text


# ---------------------------------------------------------------------------
# TestAdvanceBrowserQaSkill
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TestSkillDiscovery — test-skill-discovery.sh
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    """Canonical Yoke skills must be discoverable in the skill tree."""

    def test_all_operator_commands_have_skill_md(self):
        from yoke_core.domain.harness_capability_registry import safe_operator_surface

        missing = [
            command.entrypoint
            for command in safe_operator_surface()
            if not (SKILLS / command.entrypoint.split()[-1] / "SKILL.md").is_file()
        ]
        assert not missing, f"operator commands missing SKILL.md: {missing}"

    def test_refine_skill_has_correct_frontmatter(self):
        text = _read(SKILLS / "refine" / "SKILL.md")
        assert text.startswith("---"), "refine/SKILL.md must start with frontmatter"
        first_doc = text.split("---", 2)[1]
        assert "name: refine" in first_doc

    def test_polish_skill_has_correct_frontmatter(self):
        text = _read(SKILLS / "polish" / "SKILL.md")
        assert text.startswith("---")
        first_doc = text.split("---", 2)[1]
        assert "name: polish" in first_doc

    def test_command_router_references_refine_and_polish(self):
        # Router is the top-level yoke skill SKILL.md
        router = SKILLS / "SKILL.md"
        text = _read(router)
        assert "/yoke refine" in text
        assert "/yoke polish" in text

    def test_help_command_reference_includes_refine_and_polish(self):
        # Help output is rendered from the router's Command Reference table.
        router_text = _read(SKILLS / "SKILL.md")
        assert "/yoke refine PREFIX-N" in router_text
        assert "/yoke polish PREFIX-N" in router_text

    def test_codex_bootstrap_lists_refine_polish_and_usher(self):
        codex = REPO / "docs/public/guides/codex-harness.md"
        text = _read(codex)
        assert "refine" in text
        assert "polish" in text
        assert "usher" in text


# ---------------------------------------------------------------------------
class TestImplementIdentityGuard:
    """Implementation entry corroborates identity before lane mutation."""

    def test_implementation_entry_probes_identity_before_claim(self):
        text = _read_skill_corpus(SKILLS / "implement")
        assert "Defer the first work-claim acquisition to the orchestrator" in text
        assert "write-guard-identity-unresolved" in text
        assert "--session-id` must match the ambient result" in text
        assert "worktree_preflight.run_preflight` acquires the claim" in text
