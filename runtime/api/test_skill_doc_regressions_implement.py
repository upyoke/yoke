"""Implementation entry and canonical skill discovery contracts."""

from __future__ import annotations

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _read,
)


# ---------------------------------------------------------------------------
# TestAdvanceFinalizeSkill
# ---------------------------------------------------------------------------


class TestImplementEntrySkill:
    """Implement entry must derive implementation entry from the exact pin."""

    @pytest.fixture
    def entry_text(self) -> str:
        return _read(SKILLS / "implement" / "entry.md")

    def test_implementation_entry_requires_pinned_implement_source(
        self, entry_text: str
    ):
        assert "yoke workflows item get PREFIX-N --json" in entry_text
        assert "must be `implement`" in entry_text
        assert "yoke advance implementation-entry --item PREFIX-N" in entry_text
        assert "advance_hop" not in entry_text

    def test_implementation_entry_drops_raw_intermediate_examples(
        self, entry_text: str
    ):
        assert "items update {N} status refining-idea" not in entry_text
        assert "items update {N} status refined-idea" not in entry_text


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

    def test_codex_bootstrap_lists_refine_polish_and_usher(self):
        codex = REPO / "docs/public/agents/codex.md"
        text = _read(codex)
        assert "refine" in text
        assert "polish" in text
        assert "usher" in text


# ---------------------------------------------------------------------------
class TestImplementIdentityGuard:
    """Implementation entry lets the engine take the first work claim."""

    def test_implementation_entry_defers_first_claim_to_the_engine(self):
        text = _read(SKILLS / "implement" / "entry.md")
        assert "let the engine take the claim" in text
        assert text.index("yoke advance implementation-entry") < text.index(
            "yoke claims work acquire"
        )
