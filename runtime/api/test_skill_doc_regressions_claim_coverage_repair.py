"""Doc regressions for claim-coverage readiness repair.

`/yoke refine` separates recoverable File Budget / claim coverage failures
from unrecoverable ones and routes the recoverable ones to canonical claim
repair.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    SKILLS,
    _read,
)


class TestRefineRecoverableReadinessRepair:
    """`/yoke refine` distinguishes recoverable claim-coverage readiness
    failures from unrecoverable ones, routing the recoverable ones to
    canonical claim widen rather than releasing the work claim and
    exiting. The pre-edit and pre-bash path-claim guards teach the same widen.
    """

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "refine_skill": SKILLS / "refine" / "entry-and-gather.md",
            "refine_budget_recheck": SKILLS / "refine" / "survey-and-focus.md",
            "refine_readiness_repair": SKILLS / "refine" / "readiness-repair.md",
        }

    def test_refine_classifies_recoverable_readiness_codes(self, docs):
        skill = _read(docs["refine_skill"])
        repair = _read(docs["refine_readiness_repair"])
        # The handler names both recoverable codes and the unrecoverable
        # bucket so future readers cannot collapse them back into one class.
        # SKILL.md owns the dispatch; readiness-repair.md owns the table.
        combined = skill + repair
        assert "FILE_BUDGET_NOT_IN_CLAIM" in combined
        assert "CLAIM_NOT_IN_FILE_BUDGET" in combined
        assert "unrecoverable" in combined
        assert "recoverable" in combined

    def test_refine_routes_recoverable_to_canonical_claims_widen(self, docs):
        skill = _read(docs["refine_budget_recheck"])
        repair = _read(docs["refine_readiness_repair"])
        # The repair is canonical `yoke claims path widen` and preserves
        # path_claim_amendments, dispatched via the wrapped readiness command.
        assert "yoke claims path widen" in skill
        assert "yoke readiness repair-claim-coverage" in repair
        assert "--claim-id" in skill
        assert "--add-paths" in skill
        assert "--reason" in skill
        assert "--item PREFIX-N" in skill
        # CLI item args use ITEM_REF (PREFIX-N), never ITEM_NUM (global DB id).
        assert '--item "$ITEM_REF"' in repair
        assert '--item "$ITEM_NUM"' not in repair

    def test_refine_does_not_unconditionally_release_on_readiness(self, docs):
        text = _read(docs["refine_readiness_repair"])
        # Anti-regression for the original bug: a bare
        # `if [ "$?" -ne 0 ]; then ... release-work-claim ... exit 1`
        # block with no classification is the shape this guards against.
        assert "readiness-check-blocked" in text
        # The release/exit must be conditional on the unrecoverable case.
        assert "unrecoverable" in text
        # The mixed-recoverable path must NOT release; it falls through.
        assert "recoverable-mixed" in text or "continuing into refine" in text

    def test_refine_routes_pure_stale_count_to_repair_helper(self, docs):
        # refine entry distinguishes STALE_LINE_COUNT from
        # terminal failures and dispatches to the auto-repair helper
        # before releasing the claim.
        skill = _read(docs["refine_skill"])
        repair = _read(docs["refine_readiness_repair"])
        assert "[`readiness-repair.md`](readiness-repair.md)" in skill
        assert "pure_stale_count" in repair
        assert "yoke readiness repair-stale-count" in repair
        assert "STALE_LINE_COUNT" in repair
        assert "classify_readiness_issues" in repair
        # Repair keeps the work claim; only unrecoverable issues release it.
        assert "work claim stays" in repair.lower()

    def test_pre_edit_and_pre_bash_guards_already_emit_widen_remediation(self):
        """Pre-edit and pre-bash guard narratives teach canonical widen."""
        from yoke_core.domain import path_claim_bash_guard, path_claim_pre_edit_guard

        pre_edit = _read(Path(path_claim_pre_edit_guard.__file__).resolve())
        pre_bash = _read(Path(path_claim_bash_guard.__file__).resolve())
        assert "yoke claims path widen" in pre_edit
        assert "yoke claims path widen" in pre_bash

    def test_idea_body_and_sync_teaches_structured_field_function_adapter(self):
        """Idea body-and-sync teaches the typed function-call adapter
        for structured-field writes, not raw-recipe shell choreography.
        The retained CLI is the function-covered adapter
        ``yoke items structured-field replace --stdin`` (dispatches through
        ``items.structured_field.replace``).
        """
        text = _read(SKILLS / "idea" / "body-and-sync.md")
        assert "yoke items structured-field replace" in text, (
            "idea/body-and-sync.md must teach ``yoke items "
            "structured-field replace --stdin`` "
            "(function id: items.structured_field.replace)."
        )
