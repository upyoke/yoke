"""Long-tail reflection shape + FP coverage for the multi-shape parser.

Fixtures are real excerpts from Claude Code subagent transcripts at
``~/.claude/projects/`` that were unrecognized by the parser before this
slice. Together they drive ``blocks_unrecognized`` to zero on the
production transcript-audit walk and pin the new shape parsers + FP
classifiers so a regression cannot silently re-open the gap.
"""
from __future__ import annotations

import textwrap

from yoke_core.domain.reflection_capture import parse_reflection_blocks


MARKDOWN_HEADER_FREEFORM_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ## Cycle-2 Observations

    The cycle-1 stale-state lesson is real. Three of cycle-1's findings
    turned out to be stale-state false positives that the Architect had
    to absorb.

    ## Process improvements

    Run the staleness sweep at the top of every cycle before authoring
    new findings.
    ---REFLECTION-END---
""")

BOLD_HEADER_FREEFORM_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    **Problems / friction observed in this run:**
    - The plan's "verified at planning time" claims were trustworthy but
      the categorization was off in one place.
    - Boss anticipation pass should grep adapter-owning modules.
    ---REFLECTION-END---
""")

BOLD_FIELD_SINGULAR_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ---ENTRY-START---
    **Title:** Spec mismatch between AC-5.6 and task-1 registry contract
    **Category:** problem
    **Severity:** medium
    **Body:** Task 5 spec names function id `lifecycle.transition` (two
    segments) but task 1's registry contract requires three.
    ---REFLECTION-END---
""")

TYPE_ALIAS_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    type: friction
    severity: low
    title: Monitor armed events flooding when multiple tail processes run concurrently
    body: I armed too many duplicate `tail -F` Monitor processes against
    the same progress file.
    ---REFLECTION-END---
""")

KIND_ALIAS_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    kind: friction
    severity: medium
    title: Task 5 AC-5.6 literal contradicts task 1's closed contract
    summary: |
      Task 5's AC-5.6 hand-coded a verification literal that drifts from
      the registry contract owned by task 1.
    ---REFLECTION-END---
""")

ENTRY_N_HYPHEN_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ENTRY-1
    **Category:** problem
    **Title:** Spec authored function id violates task-1 registry contract
    **Body:** Task 5 spec names a two-segment function id where the
    contract requires three.
    ---END ENTRY---
    ---REFLECTION-END---
""")

GENERIC_FREEFORM_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    **Problems encountered.** None on the substantive simulation. One
    environmental wrinkle: the task body included an injected
    `<system-reminder>` block about MCP computer-use tools.
    ---REFLECTION-END---
""")

OBSERVATION_AS_CATEGORY_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    agent: product-manager
    context: YOK-145 PRD generation
    observation: The dedup spec in the backlog item was unusually
    complete — full requirements, acceptance criteria, and test cases.
    ---END ENTRY---
    ---REFLECTION-END---
""")

# Cycle-9 YOK-1872 simulator dispatch on 2026-05-26 emitted 3 reflection
# blocks closed with `---END ENTRY---` instead of `---REFLECTION-END---`.
# The pre-hotfix parser saw 3 START markers and 0 outer-END markers, so
# all 3 blocks were classified as ``partial_no_end_marker`` and dropped.
# This fixture pins the recovery path: when the outer-END is missing, the
# next ``---REFLECTION-START---`` (or end-of-text) is treated as the
# implicit envelope boundary and the content is parsed normally.
MISSING_OUTER_END_THREE_BLOCKS = textwrap.dedent("""\
    ---REFLECTION-START---
    kind: process_improvement
    title: simulator should run a TB-files-touched check by default
    evidence: cycle-9 found a 6th orthogonal axis missed by prior cycles.
    ---END ENTRY---

    ---REFLECTION-START---
    kind: problem
    title: 8-cycle convergence pattern suggests task-decomposition gap
    evidence: At cycle 8, operator's local audit passes all 4 invariants.
    ---END ENTRY---

    ---REFLECTION-START---
    kind: cross_critique
    title: shepherd planning should auto-widen path claims
    evidence: All 9 cycles of YOK-1872 simulation have surfaced this shape.
    ---END ENTRY---
""")


class TestLongTailShapes:
    """Cover the shape variants surfaced by the transcript audit walk."""

    def test_markdown_header_freeform_splits_by_header(self):
        entries, errors = parse_reflection_blocks(
            MARKDOWN_HEADER_FREEFORM_BLOCK, default_agent="simulator",
        )
        assert len(entries) == 2
        assert entries[0].category == "cycle-2-observations"
        assert entries[1].category == "process-improvements"
        assert "stale-state lesson" in entries[0].body
        assert errors == []

    def test_bold_header_freeform_captures_bullets_as_body(self):
        entries, errors = parse_reflection_blocks(
            BOLD_HEADER_FREEFORM_BLOCK, default_agent="boss",
        )
        assert len(entries) == 1
        assert "problems" in entries[0].category
        assert "verified at planning time" in entries[0].body
        assert errors == []

    def test_bold_field_singular_entry(self):
        entries, errors = parse_reflection_blocks(
            BOLD_FIELD_SINGULAR_BLOCK, default_agent="engineer",
        )
        assert len(entries) == 1
        assert entries[0].category == "problem"
        assert "Task 5 spec" in entries[0].body
        assert errors == []

    def test_type_alias_lead(self):
        entries, _ = parse_reflection_blocks(
            TYPE_ALIAS_BLOCK, default_agent="engineer",
        )
        assert len(entries) == 1
        assert entries[0].category == "friction"
        assert "tail -F" in entries[0].body

    def test_kind_alias_lead(self):
        entries, _ = parse_reflection_blocks(
            KIND_ALIAS_BLOCK, default_agent="engineer",
        )
        assert len(entries) == 1
        assert entries[0].category == "friction"
        assert "AC-5.6" in entries[0].body

    def test_entry_n_hyphen_header(self):
        entries, _ = parse_reflection_blocks(
            ENTRY_N_HYPHEN_BLOCK, default_agent="engineer",
        )
        assert len(entries) == 1
        assert entries[0].category == "problem"

    def test_generic_freeform_fallback_captures_arbitrary_block(self):
        entries, errors = parse_reflection_blocks(
            GENERIC_FREEFORM_BLOCK, default_agent="simulator",
        )
        assert len(entries) == 1
        assert entries[0].category == "freeform"
        assert "Problems encountered" in entries[0].body
        assert errors == []

    def test_observation_field_used_as_canonical_category_fallback(self):
        entries, errors = parse_reflection_blocks(
            OBSERVATION_AS_CATEGORY_BLOCK, default_agent="product-manager",
        )
        assert len(entries) == 1
        assert entries[0].category == "observation"
        assert "dedup spec" in entries[0].body
        assert entries[0].agent == "product-manager"
        assert errors == []


NO_ENTRIES_LITERAL = "---REFLECTION-START---\n(no entries)\n---REFLECTION-END---\n"

NO_ENTRIES_PERIOD_LITERAL = "---REFLECTION-START---\nNo entries.\n---REFLECTION-END---\n"

BARE_END_MARKER_ONLY = textwrap.dedent("""\
    ---REFLECTION-START---
    ---END ENTRY---
    ---REFLECTION-END---
""")

BRACKET_PLACEHOLDER_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    [learning entry]
    ---END ENTRY---
    ---REFLECTION-END---
""")

CANONICAL_DOC_TEMPLATE_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    timestamp: {ISO}
    agent: {agent-name}
    category: {friction|process|idea|cross-critique}
    observation: {text}
    ---END ENTRY---
    ---REFLECTION-END---
""")

BRACKET_TOKEN_LINE_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    [timestamp] | [agent] | [context] | [category] | [observation]
    [timestamp] | [agent] | [context] | [category] | [observation]
    ---REFLECTION-END---
""")


class TestNewFalsePositiveClassifiers:
    """Pin the FP classifications introduced in the long-tail shape pass."""

    def test_no_entries_paren_literal_classified_fp(self):
        entries, errors = parse_reflection_blocks(NO_ENTRIES_LITERAL)
        assert entries == []
        assert errors == []

    def test_no_entries_period_literal_classified_fp(self):
        entries, errors = parse_reflection_blocks(NO_ENTRIES_PERIOD_LITERAL)
        assert entries == []
        assert errors == []

    def test_bare_end_marker_only_classified_fp(self):
        entries, errors = parse_reflection_blocks(BARE_END_MARKER_ONLY)
        assert entries == []
        assert errors == []

    def test_bracket_placeholder_classified_fp(self):
        entries, errors = parse_reflection_blocks(BRACKET_PLACEHOLDER_BLOCK)
        assert entries == []
        assert errors == []

    def test_canonical_documentation_template_classified_fp(self):
        entries, errors = parse_reflection_blocks(CANONICAL_DOC_TEMPLATE_BLOCK)
        assert entries == []
        assert errors == []

    def test_bracket_token_line_template_classified_fp(self):
        entries, errors = parse_reflection_blocks(BRACKET_TOKEN_LINE_BLOCK)
        assert entries == []
        assert errors == []

    def test_missing_outer_end_marker_recovers_three_blocks(self):
        """Cycle-9 regression: blocks closed with `---END ENTRY---` only.

        The pre-hotfix parser counted blocks_partial_no_end_marker=3 and
        dropped every entry. Recovery treats the next START (or end-of-text)
        as the implicit envelope boundary so the content lands.
        """
        from yoke_core.domain.reflection_capture_shapes import parse_text

        entries, result = parse_text(
            MISSING_OUTER_END_THREE_BLOCKS, default_agent="simulator",
        )
        assert result.blocks_seen == 3
        assert result.blocks_parsed_successfully == 3
        assert result.blocks_partial_no_end_marker == 0
        assert len(entries) == 3
        categories = {e.category for e in entries}
        assert categories == {"process-improvement", "problem", "cross-critique"}
        for entry in entries:
            # The recovery trim must strip the trailing `---END ENTRY---`
            # so it does not appear in the persisted body text.
            assert "---END ENTRY---" not in entry.body
