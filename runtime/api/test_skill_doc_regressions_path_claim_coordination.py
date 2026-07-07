"""Doc regressions for path-claim coordination intake teaching.

These tests pin the prose shape that distinguishes ``coordination_only``
compatible-overlap edges from lifecycle-blocking ``activation`` dependencies in the
idea / refine intake docs and the AGENTS.md hard rule. Drift back to
the default-activation pattern would silently teach over-hard blockers
again.

Specifically the suite verifies:

* Path-claim conflict prose presents the overlap classification step
  before any directional-activation example, and reaches for
  ``coordination_only`` as the default shape for independent same-file
  edits.
* The ``yoke claims path coordination-decision-build`` helper invocation is named
  in idea and refine intake.
* No path-claim conflict-resolution doc reintroduces the bare
  ``shepherd dependency-add YOK-A YOK-B idea`` shape without an explicit
  ``--gate-point`` flag — that shape silently defaults to activation
  and was the regression vector observed in the 2026-05-13 cleanup pass.
* Skill prose and the AGENTS.md hard rule explicitly distinguish
  coordination-only compatible-overlap edges from lifecycle-blocking activation
  dependencies.
"""

from __future__ import annotations

import re

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _read,
)


PATH_CLAIM_BLOCKING = SKILLS / "idea" / "path-claim-blocking.md"
IDEA_SKILL = SKILLS / "idea" / "SKILL.md"
IDEA_BODY_AND_SYNC = SKILLS / "idea" / "body-and-sync.md"
IDEA_INFER_AND_CREATE = SKILLS / "idea" / "infer-and-create.md"
REFINE_SKILL = SKILLS / "refine" / "SKILL.md"
REFINE_READINESS_REPAIR = SKILLS / "refine" / "readiness-repair.md"
AGENTS_MD = REPO / "AGENTS.md"


DOCS_WITH_COORDINATION_GUIDANCE = (
    IDEA_BODY_AND_SYNC,
    IDEA_SKILL,
    IDEA_INFER_AND_CREATE,
    REFINE_READINESS_REPAIR,
    REFINE_SKILL,
    AGENTS_MD,
)


class TestPathClaimBlockingClassificationFirst:
    """`path-claim-blocking.md` must present classification before directional activation."""

    @pytest.fixture
    def text(self) -> str:
        return _read(PATH_CLAIM_BLOCKING)

    def test_helper_invocation_is_named(self, text: str):
        assert "yoke claims path coordination-decision-build" in text
        assert "--item" in text
        assert "--conflicting-claim" in text

    def test_coordination_only_appears_before_directional_activation(self, text: str):
        """Independent overlap → coordination_only must be taught before
        the directional activation example. AC-1 / AC-5."""
        coord_index = text.find("coordination_only")
        # `--gate-point activation` is the explicit directional example
        # the doc now requires. It must come AFTER the first
        # coordination_only mention.
        activation_index = text.find("--gate-point activation")
        assert coord_index >= 0, "coordination_only must be taught in path-claim-blocking.md"
        assert activation_index >= 0, (
            "explicit --gate-point activation example must be present so "
            "the default isn't silently activation"
        )
        assert coord_index < activation_index, (
            "coordination_only must appear before directional --gate-point "
            "activation; otherwise the doc teaches activation-by-default"
        )

    def test_no_implication_that_most_overlaps_are_serial(self, text: str):
        """The original prose said 'Most overlaps reflect a real serial ordering' —
        that wording defaulted authors to activation. AC-1 / AC-5."""
        assert "Most overlaps reflect a real serial ordering" not in text

    def test_classification_step_is_mandatory(self, text: str):
        """The doc must lead with a 'classify' step before authoring."""
        text_lower = text.lower()
        assert "classify" in text_lower
        # The classification headline must precede the first
        # `dependency-add` invocation.
        first_classify = text_lower.find("classify")
        first_dep_add = text.find("dependency-add")
        assert first_classify >= 0
        assert first_dep_add >= 0
        assert first_classify < first_dep_add


class TestPathClaimConflictDocsRequireExplicitGatePoint:
    """No path-claim conflict-resolution doc may reintroduce the bare
    `dependency-add YOK-A YOK-B idea` shape that silently defaults to
    activation. AC-2 / AC-5."""

    @pytest.mark.parametrize("doc", [
        PATH_CLAIM_BLOCKING,
        IDEA_BODY_AND_SYNC,
        IDEA_SKILL,
        IDEA_INFER_AND_CREATE,
        REFINE_READINESS_REPAIR,
        REFINE_SKILL,
    ])
    def test_no_bare_dependency_add_block(self, doc):
        """A multi-line `dependency-add` invocation must always carry
        `--gate-point` in the same code block. The pattern we forbid is
        `dependency-add <candidate> <other> <source>` on its own line
        with no `--gate-point` flag within the next two non-blank lines."""
        text = _read(doc)
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            # Detect the dependency-add invocation line, including
            # line-continuation backslash variants.
            if "dependency-add" not in line:
                continue
            if line.strip().startswith("#"):
                continue
            # Look at this line plus a small forward window for the
            # --gate-point flag.
            window = "\n".join(lines[idx:idx + 6])
            if "--gate-point" in window:
                continue
            pytest.fail(
                f"{doc.name}: dependency-add invocation at line {idx + 1} "
                "is missing --gate-point in its code block — this silently "
                "defaults to activation.\n"
                f"Offending block:\n{window}"
            )


class TestCoordinationOnlyDistinguishedFromActivation:
    """All listed docs must distinguish coordination-only compatible-overlap edges
    from lifecycle-blocking activation dependencies. AC-3."""

    @pytest.mark.parametrize("doc", list(DOCS_WITH_COORDINATION_GUIDANCE))
    def test_mentions_coordination_only(self, doc):
        text = _read(doc)
        assert "coordination_only" in text, (
            f"{doc.name}: must reference coordination_only compatible-overlap shape"
        )

    @pytest.mark.parametrize("doc", list(DOCS_WITH_COORDINATION_GUIDANCE))
    def test_mentions_activation_distinct_from_coordination(self, doc):
        """Each doc that teaches coordination_only must also reference
        activation (so the reader sees the distinction, not just one half)."""
        text = _read(doc)
        assert "activation" in text, (
            f"{doc.name}: must reference activation alongside coordination_only "
            "so the distinction is visible"
        )


class TestNoAmbiguousDepEdgeWording:
    """The phrase 'dep-edge via shepherd dependency-add' (alone, without
    naming the gate-point classification) is the regression vector AC-5
    pins against."""

    @pytest.mark.parametrize("doc", [
        PATH_CLAIM_BLOCKING,
        IDEA_BODY_AND_SYNC,
        IDEA_SKILL,
        IDEA_INFER_AND_CREATE,
        REFINE_READINESS_REPAIR,
        REFINE_SKILL,
        AGENTS_MD,
    ])
    def test_no_unqualified_dep_edge_via_dependency_add(self, doc):
        text = _read(doc)
        # The forbidden shape is the literal "dep-edge via
        # `shepherd dependency-add`" without an immediately following
        # gate-point classification.
        ambiguous = re.compile(
            r"dep-edge via\s+`?shepherd dependency-add`?",
            re.IGNORECASE,
        )
        for match in ambiguous.finditer(text):
            window = text[match.start():match.start() + 250]
            if "--gate-point" in window or "coordination_only" in window:
                # The doc qualifies the dep-edge with gate-point or
                # coordination classification — not a regression.
                continue
            pytest.fail(
                f"{doc.name}: ambiguous 'dep-edge via dependency-add' "
                "wording detected without --gate-point / coordination_only "
                "qualification — this silently defaults to activation. "
                f"Context window: {window!r}"
            )
