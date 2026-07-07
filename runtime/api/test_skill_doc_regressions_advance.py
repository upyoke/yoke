"""Doc regressions for advance finalize, browser-qa, and skill discovery.

Combines the advance-finalize and advance-browser-qa skill checks with the
skill-discovery doc regression (which depends on the same SKILLS / REPO
constants and stays small).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _read,
)


# ---------------------------------------------------------------------------
# TestAdvanceFinalizeSkill
# ---------------------------------------------------------------------------


class TestAdvanceFinalizeSkill:
    """Advance finalize docs must require a refined source for implementation entry."""

    @pytest.fixture
    def finalize_doc(self) -> Path:
        doc = SKILLS / "advance" / "finalize.md"
        assert doc.is_file()
        return doc

    def test_implementation_entry_requires_refined_source(self, finalize_doc: Path):
        text = _read(finalize_doc)
        section = re.search(
            r"## Implementation-entry requires a refined source.*?(?=^## Update Status)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        assert section is not None, (
            "advance/finalize.md missing the implementation-entry source section"
        )
        section_text = section.group(0)
        # advance_hop was deleted as dead code: the router dispatches a single
        # adjacent transition (refined-idea / planned -> implementing) and
        # --skip-refine owns the pre-refine bookkeeping fast-forward.
        assert "advance_hop" not in section_text
        assert "refined-idea" in section_text
        assert "--skip-refine" in section_text
        # Raw intermediate status writes stay claim-protected.
        assert "ClaimVerificationDenied" in section_text

    def test_implementation_entry_drops_raw_intermediate_examples(self, finalize_doc: Path):
        text = _read(finalize_doc)
        section = re.search(
            r"## Implementation-entry requires a refined source.*?(?=^## Update Status)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        assert section is not None, "advance/finalize.md missing implementation-entry section"
        section_text = section.group(0)
        assert "items update {N} status refining-idea" not in section_text
        assert "items update {N} status refined-idea" not in section_text


# ---------------------------------------------------------------------------
# TestAdvanceBrowserQaSkill
# ---------------------------------------------------------------------------


class TestAdvanceBrowserQaSkill:
    """Browser QA retry docs must persist healthy env status after polling."""

    @pytest.fixture
    def browser_qa_doc(self) -> Path:
        doc = SKILLS / "advance" / "browser-qa.md"
        assert doc.is_file()
        return doc

    @pytest.fixture
    def browser_qa_checks_doc(self) -> Path:
        doc = SKILLS / "advance" / "browser-qa-checks.md"
        assert doc.is_file()
        return doc

    def test_successful_poll_updates_env_status_to_healthy(
        self, browser_qa_doc: Path, browser_qa_checks_doc: Path
    ):
        # Parent router must reference the checks child file
        parent_text = _read(browser_qa_doc)
        assert "browser-qa-checks.md" in parent_text
        # Deployment polling and env-status logic lives in the checks child file
        checks_text = _read(browser_qa_checks_doc)
        assert 'if [ "$_deploy_status" = "healthy" ] && [ -n "$_env_id" ]; then' in checks_text
        assert (
            'yoke ephemeral-env update "$_env_id" status "healthy"'
            in checks_text
        )
        assert "- `healthy` → env record updated to `healthy`, proceed" in checks_text


# ---------------------------------------------------------------------------
# TestSkillDiscovery — test-skill-discovery.sh
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    """Canonical Yoke skills must be discoverable in the skill tree."""

    OPERATOR_COMMANDS = (
        "idea",
        "shepherd",
        "conduct",
        "usher",
        "doctor",
        "freeze",
        "thaw",
        "resync",
        "curate",
        "wrapup",
        "refine",
        "polish",
        "help",
        "do",
        "charge",
        "feed",
        "strategize",
        "onboard-project",
    )

    def test_all_operator_commands_have_skill_md(self):
        missing = [
            cmd for cmd in self.OPERATOR_COMMANDS
            if not (SKILLS / cmd / "SKILL.md").is_file()
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
        assert "/yoke refine YOK-N" in router_text
        assert "/yoke polish YOK-N" in router_text

    def test_codex_bootstrap_lists_refine_polish_and_usher(self):
        codex = REPO / "CODEX.md"
        if not codex.is_file():
            pytest.skip("CODEX.md not present in this checkout")
        text = _read(codex)
        assert "refine" in text
        assert "polish" in text
        assert "usher" in text


# ---------------------------------------------------------------------------
# per-skill-family function-call expectations for advance.
# Advance is the canonical surface for the work-claim and lifecycle-
# transition function families. Each adapter below dispatches through
# ``yoke_function_dispatch`` per the registry inventory.
# ---------------------------------------------------------------------------


class TestAdvanceTeachesFunctionCallAdapters:
    """Advance prose must teach the typed claim + lifecycle adapters.

    The function-call surfaces this assertion encodes:

    * ``claims.work.release`` -> ``service_client release-work-claim``
      (release at advance finalize / hop boundaries).
    * ``items.scalar.update`` -> ``db_router items update {N} <field>``
      for ``deployed_to`` and similar final-state writes the operator
      surface still owns.
    * ``lifecycle.transition.execute`` for the single adjacent
      implementation-entry transition + the full advance phase dispatch
      for the target status (no intermediate-hop helper).
    """

    def test_finalize_teaches_refined_source_and_skip_refine(self):
        text = _read(SKILLS / "advance" / "finalize.md")
        # advance_hop was deleted (dead code); finalize.md must teach the
        # replacement contract — a refined source plus the --skip-refine
        # fast-forward — and must not resurrect the removed module name.
        assert "advance_hop" not in text, (
            "advance/finalize.md must not reference the deleted advance_hop module."
        )
        assert "--skip-refine" in text
        assert "refined-idea" in text

    def test_finalize_teaches_release_work_claim_adapter(self):
        text = _read(SKILLS / "advance" / "finalize.md")
        assert "yoke claims work release" in text, (
            "advance/finalize.md must teach yoke claims work release "
            "(function id: claims.work.release)."
        )

    def test_finalize_teaches_scalar_update_adapter(self):
        text = _read(SKILLS / "advance" / "finalize.md")
        # ``items update {N} deployed_to ...`` dispatches through
        # ``items.scalar.update``; this is the retained CLI shape after
        # the function-call cutover.
        assert "items update" in text and "deployed_to" in text, (
            "advance/finalize.md must teach the deployed_to scalar "
            "update via items update (function id: items.scalar.update)."
        )
