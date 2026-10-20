"""Doc regressions for refine and polish skill ordering.

Ports ``test-refine-polish-skill.sh`` plus the polish activation-ordering
regressions that share the polish skill bundle.
"""

from __future__ import annotations

import re

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
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
    def skill_doc(self, request) -> tuple[str, "object", "object"]:
        name = request.param
        doc = SKILLS / name / "SKILL.md"
        assert doc.is_file()
        release_doc = {
            "refine": SKILLS / "refine" / "update-protocol.md",
            "polish": SKILLS / "polish" / "advance.md",
        }[name]
        return name, doc, release_doc

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
        name, _, release_doc = skill_doc
        release_lines = [
            line
            for line in _read(release_doc).splitlines()
            if "yoke claims work release" in line
        ]
        assert release_lines, f"{name}: missing yoke claims work release"
        assert any("completed" in line for line in release_lines)

    def test_releases_claim_before_final_output(self, skill_doc):
        name, _, release_doc = skill_doc
        text = _read(release_doc)
        release_at = text.rfind("yoke claims work release")
        report_at = text.find("Report", release_at)
        assert release_at >= 0, f"{name}: missing yoke claims work release"
        assert report_at > release_at, (
            f"{release_doc.name}: the final report must follow the claim release"
        )


class TestRefineItemReferenceResolution:
    """Refine resolves item identity and behavior from the immutable pin."""

    def test_refine_resolves_once_through_the_registered_pin_reader(self):
        skill = _read_refine_skill(SKILLS / "refine" / "SKILL.md")
        context = _read(SKILLS / "refine" / "workflow-context.md")
        gather = _read(SKILLS / "refine" / "entry-and-gather.md")

        assert "`ITEM_REF` is the public PREFIX-N" in context
        assert 'yoke workflows item get "$ITEM_REF" --json' in context
        assert "yoke workflows version get" in context
        assert '["result"]["item_id"]' not in context
        for field in (
            "body",
            "spec",
            "design_spec",
            "technical_plan",
            "worktree_plan",
            "shepherd_caveats",
        ):
            assert f"`{field}`" in gather
        assert '--item "$ITEM_REF"' in skill

    def test_refine_does_not_hand_parse_a_retired_prefix(self):
        text = _read_refine_skill(SKILLS / "refine" / "SKILL.md")

        assert "[Ss][Uu][Nn]" not in text
        assert "s/^[Ss][Uu][Nn]-//" not in text


# ---------------------------------------------------------------------------
# TestPolishActivationOrdering
# ---------------------------------------------------------------------------


class TestPolishActivationOrdering:
    """Polish must claim and enter its bound stage before context gathering."""

    def test_claim_before_gather_context(self):
        skill = _read(SKILLS / "polish" / "SKILL.md")
        assert skill.find("(parse-and-claim.md)") < skill.find("(context.md)")
        parse = _read(SKILLS / "polish" / "parse-and-claim.md")
        assert "Claim before any other read" in parse
        assert parse.find("yoke claims work acquire") < parse.find(
            "yoke workflows item get"
        )

    def test_bound_status_transition_in_activation_block(self):
        parse = _read(SKILLS / "polish" / "parse-and-claim.md")
        assert "At the entry stage, take the one declared forward edge" in parse
        assert "`yoke lifecycle transition`" in parse


class TestPolishVerificationFailureOwnership:
    """Current verification failures are not punted to future work."""

    def test_future_planned_claim_is_not_verification_waiver(self):
        text = " ".join(_read(REPO / "AGENTS.md").split())

        assert "Current-item verification failures belong to the current item" in text
        assert "a future item or planned path claim is not a waiver" in text
        assert "Use dependency and claim reconciliation before override" in text
        assert "Do not use `path-claim-override` for a planned future claim" in text


class TestPolishItemReferenceResolution:
    """Polish resolves item identity from the immutable pin, like refine."""

    def test_polish_resolves_once_through_the_registered_pin_reader(self):
        parse = _read(SKILLS / "polish" / "parse-and-claim.md")
        context = _read(SKILLS / "polish" / "context.md")
        assert "yoke workflows item get PREFIX-N --json" in parse
        assert '["result"]["item_id"]' not in parse
        assert "s/^[Ss][Uu][Nn]-//" not in parse
        assert "s/^[Ss][Uu][Nn]-//" not in context

    def test_polish_persists_test_results_after_verification(self):
        text = _read(SKILLS / "polish" / "verify-and-commit.md")
        assert "yoke items structured-field replace PREFIX-N" in text
        assert "--field test_results" in text


# ---------------------------------------------------------------------------
# per-skill-family function-call expectations.
# Refine prose must teach the typed function-call adapters for additive
# transforms and DB-claim amendments.
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
        # Additive transforms dispatch through
        # ``items.structured_field.append_addendum``.
        assert "yoke items structured-field append-addendum" in text, (
            "refine/update-protocol.md must teach the append-addendum "
            "adapter (items.structured_field.append_addendum)."
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
        assert "Typed writes only; never shell-transform a field" in text


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
        assert "yoke claims work acquire --item PREFIX-N --reason polish_run" in text, (
            "polish bundle must teach the claim acquire adapter "
            "(function id: claims.work.acquire)."
        )
