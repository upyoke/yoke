"""Tests for the freeform fallback parser used by `reflection_capture`.

The canonical canonical-shape coverage lives in the sibling
`test_reflection_capture.py`. These tests pin the freeform fallback that
accepts subagent reflection blocks emitted as `UPPERCASE_CATEGORY: body`
lines separated by `---END ENTRY---` (no `---BEGIN ENTRY---`).
"""
from __future__ import annotations

import textwrap

from yoke_core.domain.reflection_capture import (
    capture_reflections,
    parse_reflection_blocks,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)


FREEFORM_BLOCK = textwrap.dedent("""\
    Some preamble from the subagent.

    ---REFLECTION-START---

    PROBLEM: The cmd_register handler was at the 350-line ceiling, leaving
    no headroom for the overlap-denial delegation. Cost: 4 turns trimming.
    ---END ENTRY---

    PROCESS_IMPROVEMENT: File Budget entries should include argparse-owning
    leaf modules, not just the dispatcher shim.
    ---END ENTRY---

    GAME_CHANGING_IDEA: Generate one --help subprocess test per registered
    CLI adapter from the dispatch table.
    ---END ENTRY---

    CROSS_AGENT_CRITIQUE: Architect anticipation pass should grep cmd_*
    handlers to widen path-claims for the argparse-owning module.
    ---END ENTRY---

    ---REFLECTION-END---
""")

FREEFORM_END_ONLY_NO_HEADS = textwrap.dedent("""\
    ---REFLECTION-START---
    just some prose without a category-led head
    ---END ENTRY---
    ---REFLECTION-END---
""")


def _make_reflection_db():
    conn = connect_disposable_test_db()
    execute_schema_script(conn, """\
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            name TEXT,
            public_item_prefix TEXT DEFAULT 'YOK'
        );
        INSERT INTO projects (id, slug, name, public_item_prefix)
        VALUES (1, 'yoke', 'Yoke', 'YOK');
        CREATE TABLE ouroboros_entries (
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            agent TEXT NOT NULL,
            context TEXT,
            category TEXT NOT NULL,
            body TEXT NOT NULL,
            reviewed_at TEXT,
            archived_at TEXT,
            project_id INTEGER,
            created_at TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.commit()
    return conn


class TestParseFreeformBlocks:
    def test_block_extracts_all_entries(self):
        entries, errors = parse_reflection_blocks(FREEFORM_BLOCK, default_agent="engineer")
        assert len(entries) == 4
        assert len(errors) == 0

    def test_category_normalised_to_kebab(self):
        entries, _ = parse_reflection_blocks(FREEFORM_BLOCK, default_agent="engineer")
        assert [e.category for e in entries] == [
            "problem",
            "process-improvement",
            "game-changing-idea",
            "cross-agent-critique",
        ]

    def test_uses_default_agent_and_empty_context(self):
        entries, _ = parse_reflection_blocks(FREEFORM_BLOCK, default_agent="engineer")
        for e in entries:
            assert e.agent == "engineer"
            assert e.context == ""

    def test_preserves_multiline_body(self):
        entries, _ = parse_reflection_blocks(FREEFORM_BLOCK, default_agent="engineer")
        assert "no headroom" in entries[0].body
        assert "\n" in entries[0].body

    def test_end_markers_but_no_heads_captured_as_freeform(self):
        """Blocks with ``---END ENTRY---`` separators but no parseable heads
        are captured by the generic freeform fallback as a single
        ``freeform``-category entry rather than dropped, so the subagent's
        bounded content survives.
        """
        entries, errors = parse_reflection_blocks(FREEFORM_END_ONLY_NO_HEADS)
        assert len(entries) == 1
        assert entries[0].category == "freeform"
        assert "just some prose" in entries[0].body
        assert errors == []


class TestCaptureFreeform:
    def test_end_to_end_persists_all_entries(self):
        conn = _make_reflection_db()
        result = capture_reflections(
            FREEFORM_BLOCK,
            default_agent="engineer",
            project="yoke",
            _conn=conn,
        )
        assert result.entries_parsed == 4
        assert result.entries_persisted == 4
        assert result.errors == []
        rows = conn.execute(
            "SELECT category, agent FROM ouroboros_entries ORDER BY id"
        ).fetchall()
        assert [(r["category"], r["agent"]) for r in rows] == [
            ("problem", "engineer"),
            ("process-improvement", "engineer"),
            ("game-changing-idea", "engineer"),
            ("cross-agent-critique", "engineer"),
        ]
        conn.close()


# Shape observed live in engineer output 2026-05-15:
# lowercase ``category:`` key, sibling ``observation:`` /
# ``proposed_improvement:`` keys folded into the body, ``---END ENTRY---``
# terminator, no ``---BEGIN ENTRY---``. Before the hotfix, capture
# rejected the block with ``no parseable category-led entries``.
LOWERCASE_CATEGORY_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---

    category: friction
    observation: The session-bootstrap context dump included an entire
    `<system-reminder>` block for `session.md` that runs ~250 lines.
    proposed_improvement: Add a subagent-context-trimming render pass to
    the bootstrap-packets renderer.
    ---END ENTRY---

    category: process_improvement
    observation: The path-claim widening flow took 3 separate calls.
    proposed_improvement: glob-scoped widen for a focused refactor lane.
    ---END ENTRY---

    ---REFLECTION-END---
""")


class TestLowercaseCategoryKey:
    """Cover the task-002 engineer shape: ``category: <name>`` key plus
    sibling ``observation:`` / ``proposed_improvement:`` body keys.
    """

    def test_block_extracts_both_entries(self):
        entries, errors = parse_reflection_blocks(
            LOWERCASE_CATEGORY_BLOCK, default_agent="engineer"
        )
        assert len(entries) == 2
        assert errors == []

    def test_category_is_lowercased_and_kebab(self):
        entries, _ = parse_reflection_blocks(
            LOWERCASE_CATEGORY_BLOCK, default_agent="engineer"
        )
        assert [e.category for e in entries] == [
            "friction",
            "process-improvement",
        ]

    def test_body_preserves_sibling_keys(self):
        entries, _ = parse_reflection_blocks(
            LOWERCASE_CATEGORY_BLOCK, default_agent="engineer"
        )
        # The body must keep the observation: / proposed_improvement:
        # keys so the persisted entry reads coherently downstream.
        assert "observation:" in entries[0].body
        assert "proposed_improvement:" in entries[0].body
        # The category-naming line is consumed and NOT echoed in body.
        assert "category:" not in entries[0].body

    def test_end_to_end_persists(self):
        conn = _make_reflection_db()
        result = capture_reflections(
            LOWERCASE_CATEGORY_BLOCK,
            default_agent="engineer",
            project="yoke",
            _conn=conn,
        )
        assert result.entries_parsed == 2
        assert result.entries_persisted == 2
        assert result.errors == []
        rows = conn.execute(
            "SELECT category FROM ouroboros_entries ORDER BY id"
        ).fetchall()
        assert [r["category"] for r in rows] == [
            "friction",
            "process-improvement",
        ]
        conn.close()


# Long-tail shape + new false-positive coverage lives in
# test_reflection_capture_long_tail.py — kept in a sibling file so this
# module stays under the authored-file line cap.
# ---------------------------------------------------------------------------
