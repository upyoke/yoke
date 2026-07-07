"""Tests for the PostToolUse Agent-tool hook (YOK-1832, AC-9).

Four canonical scenarios per spec:
1. Agent + valid REFLECTION block -> entries persisted, ReflectionCaptureHookFired emitted.
2. Agent + response with no REFLECTION delimiters -> no-op, AUDIT_ONLY return.
3. Non-Agent tool_name -> fail-open, AUDIT_ONLY immediately.
4. Malformed entry inside an otherwise-valid block -> errors recorded,
   valid siblings persisted, hook returns AUDIT_ONLY (non-blocking).
"""
from __future__ import annotations

import textwrap
from unittest.mock import patch

from yoke_core.domain import reflection_capture_hook
from yoke_core.domain.reflection_capture_hook import (
    EVENT_FIRED, EVENT_UNHANDLED, evaluate,
)
from yoke_core.domain.reflection_capture_shapes import CaptureResult
from runtime.harness.hook_runner.types import HookContext, Next, Outcome


VALID_BLOCK = textwrap.dedent("""\
    Subagent output preamble...

    ---REFLECTION-START---
    ---BEGIN ENTRY---
    timestamp: 2026-05-22T00:00:00Z
    agent: engineer
    context: YOK-1832 task hook-tests
    category: friction
    The four-scenario hook test surface anchors the AC-9 contract so a
    regression in the hook is detected before it lands on main.
    ---END ENTRY---
    ---REFLECTION-END---
""")

MALFORMED_BLOCK = textwrap.dedent("""\
    ---REFLECTION-START---
    ---BEGIN ENTRY---
    timestamp: 2026-05-22T00:00:00Z
    agent: engineer
    context: YOK-1832
    category: idea
    Valid sibling entry.
    ---END ENTRY---
    ---BEGIN ENTRY---
    agent: engineer
    This entry is missing the required category field.
    ---END ENTRY---
    ---REFLECTION-END---
""")

NO_REFLECTION = "Subagent emitted no reflection block this turn."


def _agent_context(tool_response, *, subagent_type="yoke-engineer") -> HookContext:
    return HookContext(
        event_name="PostToolUse",
        executor_family="claude",
        executor_surface="claude-code",
        payload={
            "tool_name": "Agent",
            "tool_input": {"subagent_type": subagent_type},
            "tool_response": tool_response,
        },
        tool_name="Agent",
        cwd=None,
        session_id="test-session",
        item_id=None,
    )


class _CapturedEvents:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event_name, payload, session_id):
        self.events.append((event_name, payload))


class TestAgentValidBlock:
    def test_emits_fired_event_with_structured_counts(self):
        captured = _CapturedEvents()
        fake_result = CaptureResult(
            blocks_seen=1, blocks_parsed_successfully=1,
            entries_persisted=1, entries_parsed=1,
        )
        with patch.object(reflection_capture_hook, "_emit_event", captured), \
             patch("yoke_core.domain.reflection_capture.capture_reflections",
                   return_value=fake_result):
            decision = evaluate(_agent_context({"content": VALID_BLOCK}))

        assert decision.outcome is Outcome.AUDIT_ONLY
        assert decision.next is Next.CONTINUE
        assert any(name == EVENT_FIRED for name, _ in captured.events)
        fired = next(p for name, p in captured.events if name == EVENT_FIRED)
        assert fired["blocks_seen"] == 1
        assert fired["entries_persisted"] == 1
        assert fired["role"] == "engineer"
        assert fired["subagent_type"] == "yoke-engineer"


class TestAgentNoReflectionDelimiters:
    def test_no_op_when_response_lacks_delimiters(self):
        captured = _CapturedEvents()
        with patch.object(reflection_capture_hook, "_emit_event", captured):
            decision = evaluate(_agent_context({"content": NO_REFLECTION}))
        assert decision.outcome is Outcome.AUDIT_ONLY
        assert decision.next is Next.CONTINUE
        # Hook short-circuits before capture_reflections, so no event.
        assert captured.events == []


class TestNonAgentToolName:
    def test_fails_open_for_bash(self):
        captured = _CapturedEvents()
        ctx = HookContext(
            event_name="PostToolUse",
            executor_family="claude",
            executor_surface="claude-code",
            payload={"tool_name": "Bash"},
            tool_name="Bash",
        )
        with patch.object(reflection_capture_hook, "_emit_event", captured):
            decision = evaluate(ctx)
        assert decision.outcome is Outcome.AUDIT_ONLY
        assert decision.next is Next.CONTINUE
        assert captured.events == []


class TestMalformedEntryInValidBlock:
    def test_valid_siblings_persist_errors_recorded_non_blocking(self):
        captured = _CapturedEvents()
        fake_result = CaptureResult(
            blocks_seen=1,
            blocks_parsed_successfully=1,
            entries_persisted=1,
            entries_parsed=2,
            errors=["Entry #2: missing required 'category' field"],
        )
        with patch.object(reflection_capture_hook, "_emit_event", captured), \
             patch("yoke_core.domain.reflection_capture.capture_reflections",
                   return_value=fake_result):
            decision = evaluate(_agent_context({"content": MALFORMED_BLOCK}))

        assert decision.outcome is Outcome.AUDIT_ONLY
        assert decision.next is Next.CONTINUE
        # Fired event recorded; capture is non-blocking even with errors.
        fired = next(p for name, p in captured.events if name == EVENT_FIRED)
        assert fired["error_count"] == 1


class TestUnhandledBlockEmitsUnhandledEvent:
    def test_unrecognized_block_triggers_unhandled_emit(self):
        captured = _CapturedEvents()
        fake_result = CaptureResult(
            blocks_seen=1,
            blocks_unrecognized=1,
            entries_parsed=0,
            unrecognized_block_examples=[
                {"excerpt": "completely novel shape",
                 "classification_attempt": "unrecognized_shape"},
            ],
        )
        with patch.object(reflection_capture_hook, "_emit_event", captured), \
             patch("yoke_core.domain.reflection_capture.capture_reflections",
                   return_value=fake_result):
            decision = evaluate(_agent_context({"content": "---REFLECTION-START---\n???\n---REFLECTION-END---"}))

        assert decision.outcome is Outcome.AUDIT_ONLY
        event_names = [name for name, _ in captured.events]
        assert EVENT_FIRED in event_names
        assert EVENT_UNHANDLED in event_names
        unhandled = next(p for name, p in captured.events if name == EVENT_UNHANDLED)
        assert unhandled["blocks_unrecognized"] == 1
        assert unhandled["raw_examples"][0]["excerpt"] == "completely novel shape"


class TestRoleResolution:
    def test_known_roles_map_to_canonical(self):
        from yoke_core.domain.reflection_capture_hook import _resolve_role
        assert _resolve_role("yoke-engineer") == "engineer"
        assert _resolve_role("yoke-tester") == "tester"
        assert _resolve_role("yoke-simulator") == "simulator"
        assert _resolve_role("yoke-architect") == "architect"
        assert _resolve_role("yoke-boss") == "boss"

    def test_unknown_yoke_prefix_strips_prefix(self):
        from yoke_core.domain.reflection_capture_hook import _resolve_role
        assert _resolve_role("yoke-future-role") == "future-role"

    def test_none_returns_unknown(self):
        from yoke_core.domain.reflection_capture_hook import _resolve_role
        assert _resolve_role(None) == "unknown"


class TestEmitEventSignatureRegression:
    """YOK-1870 Bug A regression: _emit_event() was calling emit_event() with a
    'payload=' kwarg that does not exist on the real signature, raising TypeError
    silently swallowed by 'except Exception: pass'. The earlier tests in this file
    patch _emit_event itself, which is exactly the mocking pattern that let the
    drift slip in. These tests exercise the real emit_event call path."""

    def test_evaluate_writes_real_event_row_without_mocking_emit_event(self, monkeypatch):
        """End-to-end through evaluate() with no mock between the hook and the
        events table. Would have failed before Phase 1 because emit_event(payload=...)
        raised TypeError that the bare except swallowed and no row was ever written."""
        import json

        from yoke_core.domain import events as events_module
        from yoke_core.domain.events_schema import _create_events_table
        from yoke_core.domain.reflection_capture_shapes import CaptureResult
        from runtime.api.fixtures import pg_testdb

        db_name = pg_testdb.create_test_database()
        conn = pg_testdb.connect_test_database(db_name)
        try:
            _create_events_table(conn)
            conn.commit()

            real_emit = events_module.emit_event

            def _emit_with_test_conn(*args, **kwargs):
                kwargs["conn"] = conn
                return real_emit(*args, **kwargs)

            monkeypatch.setattr(events_module, "emit_event", _emit_with_test_conn)

            fake_result = CaptureResult(
                blocks_seen=1, blocks_parsed_successfully=1,
                entries_persisted=1, entries_parsed=1,
            )
            with patch("yoke_core.domain.reflection_capture.capture_reflections",
                       return_value=fake_result):
                decision = evaluate(_agent_context({"content": VALID_BLOCK}))

            assert decision.outcome is Outcome.AUDIT_ONLY
            row = conn.execute(
                "SELECT event_name, envelope FROM events WHERE event_name=%s",
                (EVENT_FIRED,),
            ).fetchone()
            assert row is not None, (
                "ReflectionCaptureHookFired row missing — emit_event() either raised "
                "TypeError (signature drift) or was silently swallowed by the hook's "
                "bare except. This is the YOK-1870 Bug A regression surface."
            )
            envelope = json.loads(row["envelope"])
            assert envelope["context"]["blocks_seen"] == 1
            assert envelope["context"]["entries_persisted"] == 1
        finally:
            conn.close()
            pg_testdb.drop_test_database(db_name)

    def test_old_payload_kwarg_still_raises_typeerror(self):
        """If emit_event ever regains a 'payload=' alias, the regression
        protection in this test loses meaning. Catch that drift here so a
        future-fix-the-wrong-way refactor can't silently re-enable Bug A."""
        import pytest

        from yoke_core.domain.events import emit_event

        with pytest.raises(TypeError):
            emit_event(
                "ReflectionCaptureHookFiredTestSentinel",
                payload={"blocks_seen": 0},
                session_id="test",
            )


class TestFullResponseTextExtraction:
    def test_extracts_full_content_list_no_truncation(self):
        from yoke_core.domain.reflection_capture_hook import _extract_full_response_text
        long_text = "A" * 8192
        response = {"content": [{"text": long_text}]}
        result = _extract_full_response_text(response)
        assert len(result) == 8192
        assert result == long_text

    def test_extracts_string_content(self):
        from yoke_core.domain.reflection_capture_hook import _extract_full_response_text
        response = {"content": "plain string content"}
        assert _extract_full_response_text(response) == "plain string content"

    def test_handles_bare_string_response(self):
        from yoke_core.domain.reflection_capture_hook import _extract_full_response_text
        assert _extract_full_response_text("bare string") == "bare string"

    def test_handles_none_response(self):
        from yoke_core.domain.reflection_capture_hook import _extract_full_response_text
        assert _extract_full_response_text(None) == ""

    def test_handles_raw_list_response(self):
        """Anthropic API tool-result content is a list of text parts; if
        Claude Code ever passes that list directly as ``tool_response``
        (instead of wrapping it in ``{"content": [...]}``), the extractor
        must still concatenate the text. Pre-hotfix this returned ""."""
        from yoke_core.domain.reflection_capture_hook import _extract_full_response_text
        raw_list = [
            {"type": "text", "text": "---REFLECTION-START---\nbody\n---REFLECTION-END---"},
            {"type": "text", "text": "<usage>"},
        ]
        text = _extract_full_response_text(raw_list)
        assert "REFLECTION-START" in text
        assert "<usage>" in text

    def test_emit_event_failure_writes_to_stderr_not_silent(self, capsys):
        """YOK-1870 regression: emit failures must not be silent.

        The pre-fix bare ``except Exception: pass`` hid a 3-day production
        outage where every ``_emit_event`` call raised ``TypeError`` from a
        ``payload=`` kwarg typo. Force a failure and confirm the exception
        type lands on stderr.
        """
        import yoke_core.domain.reflection_capture_hook as hook_mod
        from yoke_core.domain import events as events_mod

        def boom(*args, **kwargs):
            raise RuntimeError("simulated emit failure")

        original = events_mod.emit_event
        events_mod.emit_event = boom
        try:
            hook_mod._emit_event("ReflectionCaptureHookFired", {"k": "v"}, "sid")
        finally:
            events_mod.emit_event = original
        captured = capsys.readouterr()
        assert "_emit_event failed" in captured.err
        assert "RuntimeError" in captured.err
