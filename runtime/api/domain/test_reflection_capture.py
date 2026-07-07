"""Parse + end-to-end tests for yoke_core.domain.reflection_capture.

Regression coverage for the Conduct reflection-capture path:
- Parsing preserves all extracted fields (timestamp, agent, context, category, body)
- Multiline bodies are preserved intact
- Subagent-supplied context is NOT overwritten with a hardcoded placeholder
- Missing fields are handled gracefully with clear errors
- End-to-end capture round-trips correctly
- Failure modes are surfaced deterministically

Persistence-layer tests (persist_entries dedup + error paths) live in the
sibling test_reflection_capture_persist.py.
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ENGINEER_BLOCK = textwrap.dedent("""\
    Some task output before the reflection...

    ---REFLECTION-START---
    ---BEGIN ENTRY---
    timestamp: 2026-04-12T10:30:00Z
    agent: engineer
    context: YOK-1216 task 3
    category: friction
    The worktree re-entry path required reading three separate
    doc files just to understand the flow. This could be
    consolidated into a single dispatch table.
    ---END ENTRY---
    ---BEGIN ENTRY---
    timestamp: 2026-04-12T10:31:00Z
    agent: engineer
    context: conduct epic YOK-9999
    category: idea
    A shared reflection-capture helper would eliminate the
    duplicated parsing logic across conduct, shepherd, and plan.
    ---END ENTRY---
    ---REFLECTION-END---
""")

TESTER_BLOCK = textwrap.dedent("""\
    Tester verdict: PASS

    ---REFLECTION-START---
    ---BEGIN ENTRY---
    timestamp: 2026-04-12T11:00:00Z
    agent: tester
    context: review YOK-1216
    category: cross-critique
    The Engineer's test coverage was thorough but missed
    the edge case where no reflection block is present.
    This is a multi-line observation that spans
    several lines to test multiline preservation.
    ---END ENTRY---
    ---REFLECTION-END---
""")

NO_REFLECTION = "Just normal output with no reflection markers."

EMPTY_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ---REFLECTION-END---
""")

MALFORMED_ENTRY = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    agent: engineer
    This entry has no category field.
    ---END ENTRY---
    ---REFLECTION-END---
""")

EMPTY_BODY_ENTRY = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    agent: engineer
    category: problem
    ---END ENTRY---
    ---REFLECTION-END---
""")

# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestParseReflectionBlocks:
    def test_engineer_block_extracts_two_entries(self):
        entries, errors = parse_reflection_blocks(ENGINEER_BLOCK)
        assert len(entries) == 2
        assert len(errors) == 0

    def test_preserves_timestamp(self):
        entries, _ = parse_reflection_blocks(ENGINEER_BLOCK)
        assert entries[0].timestamp == "2026-04-12T10:30:00Z"
        assert entries[1].timestamp == "2026-04-12T10:31:00Z"

    def test_preserves_agent(self):
        entries, _ = parse_reflection_blocks(ENGINEER_BLOCK)
        assert entries[0].agent == "engineer"
        assert entries[1].agent == "engineer"

    def test_preserves_context_not_hardcoded(self):
        """FR-2: subagent-supplied context must NOT be overwritten."""
        entries, _ = parse_reflection_blocks(ENGINEER_BLOCK)
        assert entries[0].context == "YOK-1216 task 3"
        assert entries[1].context == "conduct epic YOK-9999"

    def test_preserves_category(self):
        entries, _ = parse_reflection_blocks(ENGINEER_BLOCK)
        assert entries[0].category == "friction"
        assert entries[1].category == "idea"

    def test_preserves_multiline_body(self):
        """FR-2 / AC-6: multiline body text must be preserved intact."""
        entries, _ = parse_reflection_blocks(ENGINEER_BLOCK)
        assert "worktree re-entry path" in entries[0].body
        assert "\n" in entries[0].body  # multiline preserved

    def test_tester_block_extracts_one_entry(self):
        entries, errors = parse_reflection_blocks(TESTER_BLOCK)
        assert len(entries) == 1
        assert len(errors) == 0

    def test_tester_multiline_body_preserved(self):
        """AC-6: Tester block with multiline observations."""
        entries, _ = parse_reflection_blocks(TESTER_BLOCK)
        body = entries[0].body
        assert "multi-line observation" in body
        assert "several lines" in body
        assert body.count("\n") >= 2

    def test_tester_non_default_context(self):
        """AC-6: non-default context value is preserved."""
        entries, _ = parse_reflection_blocks(TESTER_BLOCK)
        assert entries[0].context == "review YOK-1216"

    def test_no_reflection_returns_empty(self):
        entries, errors = parse_reflection_blocks(NO_REFLECTION)
        assert len(entries) == 0
        assert len(errors) == 0

    def test_empty_block_is_truthful_noop(self):
        """A REFLECTION block with no entries is a no-op, not an error."""
        entries, errors = parse_reflection_blocks(EMPTY_BLOCK)
        assert len(entries) == 0
        assert len(errors) == 0

    def test_missing_category_returns_error(self):
        entries, errors = parse_reflection_blocks(MALFORMED_ENTRY)
        assert len(entries) == 0
        assert len(errors) == 1
        assert "missing required 'category'" in errors[0]

    def test_empty_body_returns_error(self):
        entries, errors = parse_reflection_blocks(EMPTY_BODY_ENTRY)
        assert len(entries) == 0
        assert len(errors) == 1
        assert "empty body" in errors[0]

    def test_default_agent_used_when_not_specified(self):
        block = textwrap.dedent("""\
            ---REFLECTION-START---
            ---BEGIN ENTRY---
            category: problem
            Something went wrong.
            ---END ENTRY---
            ---REFLECTION-END---
        """)
        entries, _ = parse_reflection_blocks(block, default_agent="simulator")
        assert entries[0].agent == "simulator"

    def test_default_timestamp_generated_when_missing(self):
        block = textwrap.dedent("""\
            ---REFLECTION-START---
            ---BEGIN ENTRY---
            agent: tester
            category: idea
            A good idea here.
            ---END ENTRY---
            ---REFLECTION-END---
        """)
        entries, _ = parse_reflection_blocks(block)
        assert entries[0].timestamp  # not empty
        assert "T" in entries[0].timestamp  # ISO format


# ---------------------------------------------------------------------------
# End-to-end capture tests
# ---------------------------------------------------------------------------

def _make_reflection_db():
    """Create a disposable test DB with the ouroboros_entries table."""
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

class TestCaptureReflections:
    def test_engineer_end_to_end(self):
        conn = _make_reflection_db()

        result = capture_reflections(
            ENGINEER_BLOCK,
            default_agent="engineer",
            project="yoke",
            _conn=conn,
        )

        assert result.entries_parsed == 2
        assert result.entries_persisted == 2
        assert result.errors == []

        rows = conn.execute("SELECT * FROM ouroboros_entries ORDER BY id").fetchall()
        assert len(rows) == 2
        # Verify context was NOT overwritten with hardcoded placeholder
        assert rows[0]["context"] == "YOK-1216 task 3"
        assert rows[1]["context"] == "conduct epic YOK-9999"
        conn.close()

    def test_tester_end_to_end(self):
        conn = _make_reflection_db()

        result = capture_reflections(
            TESTER_BLOCK,
            default_agent="tester",
            project="yoke",
            _conn=conn,
        )

        assert result.entries_parsed == 1
        assert result.entries_persisted == 1

        row = conn.execute("SELECT * FROM ouroboros_entries WHERE id=1").fetchone()
        assert row["context"] == "review YOK-1216"
        assert "multi-line observation" in row["body"]
        conn.close()

    def test_no_reflection_truthful_noop(self):
        """AC-7: no false success when no block present."""
        result = capture_reflections(NO_REFLECTION)
        assert result.entries_parsed == 0
        assert result.entries_persisted == 0
        assert result.errors == []

    def test_malformed_entry_surfaces_error(self):
        """AC-7: capture failure surfaced deterministically."""
        result = capture_reflections(MALFORMED_ENTRY)

        assert result.entries_parsed == 0
        assert result.entries_persisted == 0
        assert len(result.errors) == 1
        assert "missing required 'category'" in result.errors[0]

    def test_hardcoded_context_regression(self):
        """AC-5: fails if context is overwritten with hardcoded 'conduct YOK-...'."""
        entries, _ = parse_reflection_blocks(ENGINEER_BLOCK)
        for entry in entries:
            # The old placeholder was 'conduct YOK-${_id}'
            assert not entry.context.startswith("conduct YOK-"), (
                f"Context '{entry.context}' looks like the old hardcoded placeholder"
            )
