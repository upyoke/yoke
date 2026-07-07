"""Tests for the PM/PD field-note marker bridge (AC-22 / Task 012).

Covers ``reflection_capture_field_note.dispatch_markers_for_entry`` end
to end through ``capture_reflections``:

- Marker present + valid kind → ``ouroboros.field_note.append`` dispatched.
- Marker absent → no field-note dispatched.
- Marker present + invalid kind → ``ReflectionMarkerParseFailed`` event
  emitted (F-4 recovery); reflection still captured as plain entry; no
  field-note dispatched.

The marker-parse unit tests for the regex live alongside the integration
cases here so the bridge module's contract is in one place; the broader
``reflection_capture`` parsing suite stays in ``test_reflection_capture``.
"""
from __future__ import annotations

import textwrap

from yoke_core.domain.reflection_capture import capture_reflections
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PM_VALID_MARKER_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    timestamp: 2026-05-14T12:00:00Z
    agent: product-manager
    context: scoping YOK-1700
    category: friction
    field_note_kind: failed
    The R-CL-03 recipe instructed --remove but the actual flag is --drop-paths.
    Tried the documented form first and hit unknown-argument; only got unstuck
    after grepping the CLI source.
    ---END ENTRY---
    ---REFLECTION-END---
""")

PD_INVALID_MARKER_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    timestamp: 2026-05-14T12:00:00Z
    agent: product-designer
    context: spec drafting YOK-1701
    category: idea
    field_note_kind: bogus
    The recipe lookup table needs a "design review" kind for PD findings.
    ---END ENTRY---
    ---REFLECTION-END---
""")

PLAIN_BLOCK_NO_MARKER = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    timestamp: 2026-05-14T12:00:00Z
    agent: engineer
    context: YOK-1700 task 3
    category: friction
    Worktree re-entry required reading three doc files. Consolidation
    into a single dispatch table would help.
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


def _patch_dispatch_capture(monkeypatch):
    """Patch yoke_function_dispatch.dispatch to capture calls."""
    from yoke_core.domain import yoke_function_dispatch

    calls: list = []

    class _StubResponse:
        success = True
        error = None
        result = {}

    def fake_dispatch(request, ambient_session_id=None, **kwargs):
        calls.append({
            "function": request.function,
            "payload": dict(request.payload),
            "session_id": request.actor.session_id,
            "ambient_session_id": ambient_session_id,
        })
        return _StubResponse()

    monkeypatch.setattr(yoke_function_dispatch, "dispatch", fake_dispatch)
    return calls


def _patch_marker_failed_events(monkeypatch):
    """Patch the helper's events module to capture parse-failed emits."""
    from yoke_core.domain import reflection_capture_field_note as _rcfn

    emits: list = []

    def fake_emit(event_name, **kwargs):
        emits.append({"event_name": event_name, **kwargs})

        class _R:
            ok = True
            event_id = "evt-stub"
        return _R()

    monkeypatch.setattr(_rcfn._events, "emit_event", fake_emit)
    return emits


# ---------------------------------------------------------------------------
# Integration through capture_reflections
# ---------------------------------------------------------------------------

class TestFieldNoteMarkerBridge:
    """AC-22 — PM/PD reflection markers convert to ouroboros.field_note.append."""

    def test_valid_marker_dispatches_field_note(self, monkeypatch):
        conn = _make_reflection_db()
        dispatch_calls = _patch_dispatch_capture(monkeypatch)

        result = capture_reflections(
            PM_VALID_MARKER_BLOCK,
            default_agent="product-manager",
            project="yoke",
            _conn=conn,
        )

        # Reflection itself captured (plain entry behavior preserved).
        assert result.entries_parsed == 1
        assert result.entries_persisted == 1
        assert result.errors == []

        # Exactly one field-note dispatched.
        assert len(dispatch_calls) == 1
        call = dispatch_calls[0]
        assert call["function"] == "ouroboros.field_note.append"
        assert call["payload"]["kind"] == "failed"
        assert "R-CL-03" in call["payload"]["evidence"]
        conn.close()

    def test_marker_absent_does_not_dispatch(self, monkeypatch):
        """Plain reflection without marker fires no field-note."""
        conn = _make_reflection_db()
        dispatch_calls = _patch_dispatch_capture(monkeypatch)

        result = capture_reflections(
            PLAIN_BLOCK_NO_MARKER,
            default_agent="engineer",
            project="yoke",
            _conn=conn,
        )

        assert result.entries_parsed == 1
        assert result.entries_persisted == 1
        assert dispatch_calls == []
        conn.close()

    def test_invalid_marker_emits_parse_failed_no_dispatch(self, monkeypatch):
        """F-4 recovery: invalid kind → ReflectionMarkerParseFailed; field-note NOT fired."""
        conn = _make_reflection_db()
        dispatch_calls = _patch_dispatch_capture(monkeypatch)
        parse_failed_emits = _patch_marker_failed_events(monkeypatch)

        result = capture_reflections(
            PD_INVALID_MARKER_BLOCK,
            default_agent="product-designer",
            project="yoke",
            _conn=conn,
        )

        # Reflection text still captured as plain entry.
        assert result.entries_parsed == 1
        assert result.entries_persisted == 1
        # Field-note dispatch NOT fired.
        assert dispatch_calls == []
        # Exactly one ReflectionMarkerParseFailed event emitted.
        assert len(parse_failed_emits) == 1
        emit = parse_failed_emits[0]
        assert emit["event_name"] == "ReflectionMarkerParseFailed"
        assert emit["context"]["raw_value"] == "bogus"
        assert emit["context"]["agent"] == "product-designer"
        # Closed-enum surfaced for operator triage.
        assert "failed" in emit["context"]["valid_values"]
        assert "new" in emit["context"]["valid_values"]
        assert "unclear" in emit["context"]["valid_values"]
        conn.close()


# ---------------------------------------------------------------------------
# Marker parser unit tests
# ---------------------------------------------------------------------------

class TestFindMarkers:
    """Direct coverage of the marker regex."""

    def test_whitespace_and_case_tolerance(self):
        from yoke_core.domain.reflection_capture_field_note import find_markers

        body = "Some context\n  Field_Note_Kind :   New  \nMore text\n"
        markers = find_markers(body)
        assert markers == ["new"]

    def test_empty_text_returns_empty(self):
        from yoke_core.domain.reflection_capture_field_note import find_markers

        assert find_markers("") == []
        assert find_markers("Just plain text without the marker.") == []

    def test_multiple_markers_returned_in_order(self):
        from yoke_core.domain.reflection_capture_field_note import find_markers

        body = (
            "First note.\n"
            "field_note_kind: failed\n"
            "Second note.\n"
            "field_note_kind: new\n"
            "Trailing prose.\n"
        )
        assert find_markers(body) == ["failed", "new"]
