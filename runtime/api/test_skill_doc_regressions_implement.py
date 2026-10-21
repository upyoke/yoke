"""Canonical skill discovery contracts."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import (
    SKILLS,
    _read,
)


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
