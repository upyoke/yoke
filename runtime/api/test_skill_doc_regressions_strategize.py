"""Doc regression for the strategize skill — ports ``test-strategize.sh``."""

from __future__ import annotations

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    SKILLS,
    _read,
)


# ---------------------------------------------------------------------------
# TestStrategize — test-strategize.sh
# ---------------------------------------------------------------------------


class TestStrategize:
    """Strategize entry surface must keep its phase files and /do handoff."""

    STRATEGIZE_DIR = SKILLS / "strategize"

    def test_strategize_skill_exists(self):
        assert (self.STRATEGIZE_DIR / "SKILL.md").is_file()

    def test_strategize_phase_files_present(self):
        """Strategize is decomposed into phase sub-files; at least one must exist."""
        skill_dir = self.STRATEGIZE_DIR
        assert skill_dir.is_dir()
        phase_files = [
            p for p in skill_dir.iterdir()
            if p.suffix == ".md" and p.name != "SKILL.md"
        ]
        assert phase_files, (
            "strategize/ must contain at least one phase sub-file "
            "(research / propose / approve)"
        )

    def test_do_skill_references_strategize(self):
        """`/yoke do` must reference strategize in its skill tree.

        The reference can live in SKILL.md or one of its phase sub-files
        (loop.md today); either location is acceptable.
        """
        do_dir = SKILLS / "do"
        if not do_dir.is_dir():
            pytest.skip("/yoke do skill not present")
        found = False
        for md in do_dir.rglob("*.md"):
            if "strategize" in _read(md).lower():
                found = True
                break
        assert found, "/yoke do must hand off to strategize somewhere in its skill tree"

    def test_router_lists_strategize(self):
        router_text = _read(SKILLS / "SKILL.md")
        assert "/yoke strategize" in router_text

    def test_strategize_phase_files_avoid_ask_user_question(self):
        """Strategize checkpoints should stay conversational across the phase files."""
        offenders = []
        for md in self.STRATEGIZE_DIR.rglob("*.md"):
            if "AskUserQuestion" in _read(md):
                offenders.append(md.relative_to(SKILLS).as_posix())
        assert not offenders, (
            "strategize phase files must not use AskUserQuestion; "
            f"found in: {', '.join(offenders)}"
        )

    def test_strategize_tradeoff_examples_use_semantic_labels(self):
        """Tradeoff checkpoint examples should model semantic labels, not placeholders."""
        approve_text = _read(self.STRATEGIZE_DIR / "approve.md")
        finalize_text = _read(self.STRATEGIZE_DIR / "finalize.md")
        combined = f"{approve_text}\n{finalize_text}"
        assert "resolution_A" not in combined
        assert "resolution_B" not in combined

    def test_refresh_preserves_new_ids_in_structured_carry_set(self):
        """refresh must keep 'new this session' stable across summary + JSON."""
        text = _read(self.STRATEGIZE_DIR / "refresh.md")
        assert "yoke strategy carry register-new" in text
        assert "--result-json" in text
        assert "yoke strategy carry summary" in text
        assert "yoke strategy carry candidate-set" in text
        assert "--new-ids ${_carry_new_ids}" in text
        assert "_carry_total_pending=" in text
        assert "_carry_new_count=" in text

    def test_finalize_uses_module_invocation_for_claim_release(self):
        """carry marks and claim release use the function-call surface without shell glue."""
        text = _read(self.STRATEGIZE_DIR / "finalize.md")
        # Session-ID fallback chains must be eliminated
        assert '_sid="${YOKE_SESSION_ID' not in text
        assert '--session-id "$_sid"' not in text
        # Claim release uses the function-call surface. The historical
        # `python3 -m yoke_core.api.service_client release-work-claim` CLI verb
        # was migrated to the `claims.work.release` function call in the
        # operations/cleanup wave.
        assert '"function": "claims.work.release"' in text

    def test_strategize_skill_is_not_a_stub(self):
        """Guards against regression to a placeholder skill."""
        text = _read(self.STRATEGIZE_DIR / "SKILL.md")
        # A stub would be a handful of lines; real skill doc is substantial.
        assert len(text.splitlines()) > 30, (
            "strategize/SKILL.md looks like a stub — fewer than 30 lines"
        )

    def test_strategize_research_has_landscape_editorial_pressure_pass(self):
        """Research phase must flag LANDSCAPE.md bloat, not just factual drift.

        Without an editorial-pressure pass, research only corrects facts and
        strategize sessions default to append-only LANDSCAPE.md growth. The
        research file must explicitly teach the agent to flag overgrown
        sections, duplication, table-stakes observations, and clusters of
        related developments that should be summarized instead of enumerated.
        """
        text = _read(self.STRATEGIZE_DIR / "research.md").lower()
        # The five editorial moves must all be named so the agent has a
        # concrete vocabulary for the finding.
        for term in ("weave", "consolidat", "retire", "table-stakes", "summariz"):
            assert term in text, (
                f"strategize/research.md must mention '{term}' to teach "
                "LANDSCAPE.md editorial discipline (YOK-1232)"
            )
        # And density/legibility must be treated as first-class review
        # dimensions, not just factual correctness.
        assert "density" in text or "dense" in text, (
            "strategize/research.md must treat section density as a review "
            "dimension (YOK-1232)"
        )

    def test_strategize_teaches_process_claim_work_adapter(self):
        """task 015: strategize teaches the function-call adapters
        for the ``claims.process.claim`` family.

        Strategize is a process-claim surface (not item-claim) — it
        acquires the canonical ``STRATEGIZE`` process work claim before
        the research/propose/approve phase loop. The canonical agent
        CLI adapter is ``yoke claims work acquire --process STRATEGIZE``.
        """
        text = _read(self.STRATEGIZE_DIR / "SKILL.md")
        assert "yoke claims work acquire" in text, (
            "strategize/SKILL.md must teach yoke claims work acquire "
            "(function id family: claims.work.acquire / process target) "
            "for the STRATEGIZE process claim acquisition."
        )
        assert "yoke claims work release" in text, (
            "strategize/SKILL.md must teach yoke claims work release "
            "(function id: claims.work.release) so the abort + finalize "
            "contract is visible without consulting phase files."
        )

    def test_strategize_propose_has_landscape_editorial_rules(self):
        """Propose phase must make the add-vs-rewrite decision explicit.

        Without explicit weave-first and add-vs-rewrite rules, propose defaults
        to appending a fresh bullet for every new signal. The propose file must
        teach the agent to weave into existing sections first, consolidate
        before adding when a section is dense, retire stale or table-stakes
        observations, and justify any net-new bullet or paragraph.
        """
        text = _read(self.STRATEGIZE_DIR / "propose.md").lower()
        for term in ("weave", "consolidat", "retire", "table-stakes", "justif"):
            assert term in text, (
                f"strategize/propose.md must mention '{term}' to teach "
                "LANDSCAPE.md editorial discipline (YOK-1232)"
            )
        # The rewrite-vs-add decision must be explicit, not implied.
        assert "rewrite" in text, (
            "strategize/propose.md must make the add-vs-rewrite decision "
            "explicit (YOK-1232)"
        )
