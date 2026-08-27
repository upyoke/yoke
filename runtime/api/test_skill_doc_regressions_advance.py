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
    """Advance finalize must derive implementation entry from the exact pin."""

    @pytest.fixture
    def finalize_doc(self) -> Path:
        doc = SKILLS / "advance" / "finalize.md"
        assert doc.is_file()
        return doc

    def test_implementation_entry_requires_pinned_advance_source(self, finalize_doc: Path):
        text = _read(finalize_doc)
        section = re.search(
            r"## Implementation-entry requires the pinned advance source.*?(?=^## Update Status)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        assert section is not None, (
            "advance/finalize.md missing the implementation-entry source section"
        )
        section_text = section.group(0)
        # advance_hop was deleted as dead code: the router dispatches a single
        # The router dispatches one adjacent transition from the pinned
        # advance binding source; --skip-refine owns bookkeeping fast-forward.
        assert "advance_hop" not in section_text
        assert "from_stage_id" in section_text
        assert "single_implementation_lane" in section_text
        assert "--skip-refine" in section_text
        # Raw intermediate status writes stay claim-protected.
        assert "ClaimVerificationDenied" in section_text

    def test_implementation_entry_drops_raw_intermediate_examples(self, finalize_doc: Path):
        text = _read(finalize_doc)
        section = re.search(
            r"## Implementation-entry requires the pinned advance source.*?(?=^## Update Status)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        assert section is not None, "advance/finalize.md missing implementation-entry section"
        section_text = section.group(0)
        assert "items update {N} status refining-idea" not in section_text
        assert "items update {N} status refined-idea" not in section_text

    def test_skip_routing_resolves_pinned_skill_bindings(self, finalize_doc: Path):
        from yoke_core.domain import advance_skip_core

        text = _read(finalize_doc)
        assert "yoke_core.domain.advance_skip_core" in text
        assert "yoke_core.domain.lifecycle_progression" not in text
        assert "PRE_IMPLEMENTATION_STATUSES" not in text
        assert "_skill_skip_route" in text
        assert callable(advance_skip_core._skill_skip_route)
        assert "skill_bindings" in text
        assert "transitions" in text
        for retired_name in (
            "_REFINE_ROUTING",
            "_REFINE_TARGETS_ALLOWED",
            "_POLISH_TRANSIT_ALLOWED",
        ):
            assert retired_name not in text
            assert not hasattr(advance_skip_core, retired_name)


# ---------------------------------------------------------------------------
# TestAdvanceBrowserQaSkill
# ---------------------------------------------------------------------------


class TestAdvanceBrowserQaSkill:
    """Browser QA executes method-backed cases through the shared runner."""

    @pytest.fixture
    def browser_qa_doc(self) -> Path:
        doc = SKILLS / "advance" / "browser-qa.md"
        assert doc.is_file()
        return doc

    def test_materializes_and_executes_browser_method_cases(
        self, browser_qa_doc: Path,
    ):
        text = _read(browser_qa_doc)
        assert "yoke qa plan materialize" in text
        assert "browser-check" in text
        assert "browser-inspection" in text
        assert "yoke qa case run" in text


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
        "steer",
        "onboard",
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
        assert "/yoke refine PREFIX-N" in router_text
        assert "/yoke polish PREFIX-N" in router_text

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

    def test_finalize_teaches_pinned_source_and_skip_refine(self):
        text = _read(SKILLS / "advance" / "finalize.md")
        # advance_hop was deleted (dead code); finalize.md must teach the
        # replacement contract — a pinned binding source plus --skip-refine
        # fast-forward — and must not resurrect the removed module name.
        assert "advance_hop" not in text, (
            "advance/finalize.md must not reference the deleted advance_hop module."
        )
        assert "--skip-refine" in text
        assert "from_stage_id" in text
        assert "_worktree_policy" in text

    def test_implementation_entry_probes_identity_before_claim(self):
        text = _read(SKILLS / "advance" / "SKILL.md")
        assert (
            "defer the first work-claim acquisition to the orchestrator" in text
        )
        assert "write-guard-identity-unresolved" in text
        assert "--session-id` must match the ambient result" in text
        assert "worktree_preflight.run_preflight` acquires the claim" in text

    def test_finalize_teaches_release_work_claim_adapter(self):
        text = _read(SKILLS / "advance" / "finalize.md")
        assert "yoke claims work release" in text, (
            "advance/finalize.md must teach yoke claims work release "
            "(function id: claims.work.release)."
        )

    def test_finalize_teaches_scalar_update_adapter(self):
        text = _read(SKILLS / "advance" / "finalize.md")
        assert "items.scalar.update" in text and "deployed_to" in text, (
            "advance/finalize.md must teach deployed_to through the "
            "typed items.scalar.update function call."
        )
