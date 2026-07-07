"""Doc regressions for refine and polish skill ordering.

Ports ``test-refine-polish-skill.sh`` plus the polish activation-ordering
regressions that share the polish skill bundle.
"""

from __future__ import annotations

import re

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    SKILLS,
    _read,
    _read_polish_skill,
    _read_refine_skill,
)


# ---------------------------------------------------------------------------
# TestRefinePolishSkill — claim release ordering
# ---------------------------------------------------------------------------


class TestRefinePolishSkill:
    """Refine and polish must release the work claim before final output."""

    @pytest.fixture(params=["refine", "polish"])
    def skill_doc(self, request) -> tuple[str, "object", str]:
        name = request.param
        doc = SKILLS / name / "SKILL.md"
        assert doc.is_file()
        final_heading = {"refine": "### 11. Final Output", "polish": "## 14. Final Output"}[name]
        return name, doc, final_heading

    def test_no_pre_release_report_step(self, skill_doc):
        name, doc, _ = skill_doc
        text = _read(doc)
        # Refine previously used "### 8. Report"; polish previously used "### 9. Report".
        early_report_headings = (r"^### 8\. Report", r"^### 9\. Report")
        for heading in early_report_headings:
            assert not re.search(heading, text, re.MULTILINE), (
                f"{name}/SKILL.md must not have a pre-release report step "
                f"matching {heading!r}"
            )

    def test_documents_completed_claim_release(self, skill_doc):
        name, doc, _ = skill_doc
        text = _read_refine_skill(doc) if name == "refine" else _read_polish_skill(doc)
        # refine teaches the canonical agent CLI verb; polish teaches the
        # function-call surface (claims.work.release). Each branch asserts
        # its own contract.
        if name == "refine":
            assert "yoke claims work release" in text
            assert '"YOK-$ITEM_NUM"' in text
        else:
            assert "claims.work.release" in text
        assert '"completed"' in text

    def test_releases_claim_before_final_output(self, skill_doc):
        name, doc, final_heading = skill_doc
        text = _read_refine_skill(doc) if name == "refine" else _read_polish_skill(doc)
        # refine teaches the canonical agent CLI verb; polish teaches the
        # function-call surface. Pick the right anchor per skill so the
        # ordering check still measures the same structural intent
        # (release before final-output).
        release_anchor = "yoke claims work release" if name == "refine" else "claims.work.release"
        lines = text.splitlines()
        release_line = None
        final_line = None
        for idx, line in enumerate(lines, start=1):
            if release_anchor in line:
                release_line = idx  # last match wins — matches old tail -1
            if line.strip() == final_heading:
                if final_line is None:
                    final_line = idx  # first match wins — matches old head -1
        assert release_line is not None, f"{name}: missing {release_anchor!r}"
        assert final_line is not None, f"{name}: missing final-output heading"
        assert release_line < final_line, (
            f"{name}/SKILL.md releases claim at line {release_line} but "
            f"final-output step is at line {final_line}; release must come first"
        )


# ---------------------------------------------------------------------------
# TestPolishActivationOrdering
# ---------------------------------------------------------------------------


class TestPolishActivationOrdering:
    """Polish must front-load claim and status activation before context gathering.

    The activation step (claims.work.acquire — which atomically touches the
    session row inside the same transaction — plus the polishing-implementation
    lifecycle.transition) must appear as an explicit early step BEFORE any
    context gathering, diff review, or survey sections. If prompt drift moves
    the activation later, these tests fail.
    """

    @pytest.fixture
    def polish_doc(self) -> str:
        return _read_polish_skill(SKILLS / "polish" / "SKILL.md")

    def test_claim_before_gather_context(self, polish_doc: str):
        """claims.work.acquire must appear before the Gather Context heading."""
        lines = polish_doc.splitlines()
        claim_line = None
        gather_line = None
        for idx, line in enumerate(lines, start=1):
            if "claims.work.acquire" in line and claim_line is None:
                claim_line = idx
            if re.match(r"^#{2,3}\s+\d+\.\s+Gather Context", line) and gather_line is None:
                gather_line = idx
        assert claim_line is not None, "polish/SKILL.md missing claims.work.acquire"
        assert gather_line is not None, "polish/SKILL.md missing Gather Context heading"
        assert claim_line < gather_line, (
            f"polish/SKILL.md: claims.work.acquire at line {claim_line} must appear before "
            f"Gather Context at line {gather_line}"
        )

    def test_polishing_status_transition_in_activation_block(self, polish_doc: str):
        """polishing-implementation transition must be in the activation step, before Gather Context."""
        lines = polish_doc.splitlines()
        transition_line = None
        gather_line = None
        for idx, line in enumerate(lines, start=1):
            if "polishing-implementation" in line and "status" in line and transition_line is None:
                transition_line = idx
            if re.match(r"^#{2,3}\s+\d+\.\s+Gather Context", line) and gather_line is None:
                gather_line = idx
        assert transition_line is not None, (
            "polish/SKILL.md missing polishing-implementation status transition"
        )
        assert gather_line is not None, "polish/SKILL.md missing Gather Context heading"
        assert transition_line < gather_line, (
            f"polish/SKILL.md: polishing-implementation transition at line {transition_line} "
            f"must appear before Gather Context at line {gather_line}"
        )

    def test_activation_is_explicit_hard_gate(self, polish_doc: str):
        """The activation step must be labeled as a hard gate to prevent drift."""
        assert "HARD GATE" in polish_doc, (
            "polish/SKILL.md activation step must contain 'HARD GATE' language "
            "to make the ordering impossible to miss"
        )

    def test_session_touch_is_atomic_with_claim_acquire(self, polish_doc: str):
        """Session-row touch must be taught as atomic with claims.work.acquire.

        Under the function-call surface, the claim-acquire handler touches the
        session row in the same transaction; there is no separate session-touch
        step. The prose must make that atomicity explicit so agents do not
        re-introduce a free-standing session-touch invocation.
        """
        assert "claims.work.acquire" in polish_doc, (
            "polish/SKILL.md missing claims.work.acquire invocation"
        )
        # The atomic-session-touch teaching must accompany the acquire call.
        assert "touches the session row in the same transaction" in polish_doc, (
            "polish/SKILL.md must teach that claims.work.acquire atomically "
            "touches the session row in the same transaction"
        )


class TestPolishVerificationFailureOwnership:
    """Polish must not punt current verification failures to future work."""

    def test_future_planned_claim_is_not_verification_waiver(self):
        text = _read(SKILLS / "polish" / "verify-and-commit.md")

        assert "Future/planned item ownership" in text
        assert "planned path claim is not a waiver" in text
        assert "path-claim-widen" in text
        assert "dependency or claim reconciliation" in text
        assert "Do not use `path-claim-override` for a planned future claim" in text
        assert "override is last resort" in text
        assert "explicit operator approval" in text
        assert "Do not leave the worktree in a failing state" in text


# ---------------------------------------------------------------------------
# per-skill-family function-call expectations.
# These assertions encode the AC-15.1 / AC-15.4 contract for refine —
# refine prose must teach the typed function-call adapters for structured-
# field writes, additive transforms, and DB-claim amendments. The
# assertion class deliberately mirrors the inventory at
# ``service_client_structured_api_adapter_inventory.py`` so the test fails
# whenever a refine surface regresses to a non-canonical recipe.
# ---------------------------------------------------------------------------


class TestRefineTeachesFunctionCallAdapters:
    """Refine surfaces must teach the function-call adapter forms.

    The refine skill is the primary authoring surface for spec /
    technical_plan / DB-claim mutations. Each adapter below is wired
    through ``yoke_function_dispatch``; the refine prose must teach
    them so the False-Teacher Eradication Contract holds for this
    family.
    """

    def test_update_protocol_teaches_structured_field_adapter(self):
        text = _read(SKILLS / "refine" / "update-protocol.md")
        # Full-field rewrites: the yoke stdin adapter dispatches
        # through ``items.structured_field.replace``.
        assert "yoke items structured-field replace" in text, (
            "refine/update-protocol.md must teach the yoke adapter for "
            "full-field rewrites (items.structured_field.replace)."
        )
        # Additive transforms: the function-call adapter dispatches
        # through ``items.structured_field.append_addendum``.
        assert "yoke items structured-field append-addendum" in text, (
            "refine/update-protocol.md must teach the append-addendum "
            "adapter (items.structured_field.append_addendum)."
        )
        # Section append: dispatches through
        # ``items.structured_field.section_append`` /
        # ``items.progress_log.append``.
        assert "yoke items progress-log append" in text, (
            "refine/update-protocol.md must teach the progress-log append "
            "adapter (items.progress_log.append)."
        )

    def test_update_protocol_teaches_db_claim_amend_adapter(self):
        text = _read(SKILLS / "refine" / "update-protocol.md")
        # DB-claim amendments route through one unified adapter that
        # dispatches through ``db_claim.amend``.
        assert "yoke db-claim amend" in text, (
            "refine/update-protocol.md must teach the yoke db-claim "
            "amend adapter (function id: db_claim.amend)."
        )

    def test_update_protocol_rejects_read_then_upsert_choreography(self):
        text = _read(SKILLS / "refine" / "update-protocol.md")
        # The PreToolUse lint catches read-then-transform-then-write
        # shell choreography. The skill must explicitly name this
        # so authors know the function-call adapter is the path.
        assert "lint:no-structured-transform-check" in text, (
            "refine/update-protocol.md must reference the lint suppression "
            "token so authors learn the structured-field-transform shell "
            "lint by name when reading the canonical write protocol."
        )


class TestPolishTeachesFunctionCallAdapters:
    """Polish surfaces must teach the canonical claim release adapter.

    Polish closes out the implementation slice and is the canonical
    surface for ``claims.work.release``. The canonical agent CLI adapter
    is ``yoke claims work release``. The assertion reads the polish
    bundle (SKILL.md + every phase file) because polish is decomposed
    across phases; the adapter call lives in ``advance.md``.
    """

    def test_polish_bundle_teaches_release_work_claim_adapter(self):
        text = _read_polish_skill(SKILLS / "polish" / "SKILL.md")
        assert "yoke claims work release" in text, (
            "polish bundle (SKILL.md + phase files) must teach the "
            "yoke claims work release adapter (function id: "
            "claims.work.release)."
        )

    def test_polish_bundle_teaches_claim_work_adapter(self):
        text = _read_polish_skill(SKILLS / "polish" / "SKILL.md")
        assert "claim-work" in text, (
            "polish bundle must teach the claim-work adapter "
            "(function id: claims.work.claim) — claim acquisition is the "
            "polish entry contract."
        )
