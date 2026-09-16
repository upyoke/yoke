"""Routine dispatcher telemetry stays compact and failure-bounded.

``YokeFunctionCalled`` fires on every dispatched call, so anything it
copies is paid for once per call forever. These tests hold three
properties the envelope must keep:

- the result document never rides the routine event (only its size and
  digest do), so event size is independent of result size;
- a failure still carries enough to act on — code, clipped message,
  jsonpath — and nothing unbounded;
- the replay ledger is written even when telemetry emission raises,
  because the ledger is operational state and events are disposable.

Baseline this replaced: over the most recent 2,000 production
``YokeFunctionCalled`` rows (2026-09-16 20:35:32-21:36:33 UTC), the
copied result was 8,876,530 of 11,982,526 envelope characters — 74%,
averaging 4,438 of 5,991 characters per call.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict
from unittest.mock import patch

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.events_retired_name_guard import RetiredEventNameError
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_dispatch_events import emit_permission_denied
from yoke_core.domain.yoke_function_dispatch_failure_context import (
    FAILURE_TEXT_MAX_CHARS,
)
from yoke_core.domain.yoke_function_registry import register
from yoke_contracts.api.function_call import (
    FunctionError,
    FunctionWarning,
    HandlerOutcome,
)

from runtime.api.domain.test_yoke_function_dispatch import (
    _DispatcherTestBase,
    _Req,
    _Resp,
    _make_request,
    _ok_handler,
    _stable_kwargs,
)


# One comparable call's result, sized like the production heavy hitters
# (session_control.relay.list averaged ~19,600 characters per call).
_BIG_RESULT = {"sessions": [{"session_id": f"s-{n}", "note": "x" * 180}
                            for n in range(100)]}


def _big_result_handler(_request):
    return HandlerOutcome(result_payload=dict(_BIG_RESULT), primary_success=True)


def _failing_handler(_request):
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code="claim_required",
            message="C" * (FAILURE_TEXT_MAX_CHARS + 2_000),
            jsonpath="$.payload.item_id",
            recovery_hint="H" * 5_000,
        ),
    )


def _long_warning_handler(_request):
    return HandlerOutcome(
        result_payload={"status": "ok"},
        primary_success=True,
        warnings=[
            FunctionWarning(
                code="github_sync_degraded",
                step="github_sync",
                detail="D" * (FAILURE_TEXT_MAX_CHARS + 900),
            )
        ],
    )


class _CompactEventBase(_DispatcherTestBase):
    """Dispatch one registered handler and return its called-event context."""

    def _context_for(self, function_id: str, handler: Any, **reg) -> Dict[str, Any]:
        register(function_id, handler, _Req, _Resp, **_stable_kwargs(**reg))
        dispatch(_make_request(function_id))
        return self._called_context()

    def _called_context(self) -> Dict[str, Any]:
        calls = events_module.emit_event.calls  # type: ignore[attr-defined]
        called = [c for c in calls
                  if c["args"] and c["args"][0] == "YokeFunctionCalled"]
        self.assertEqual(len(called), 1)
        return called[0]["kwargs"]["context"]


class TestResultStaysOutOfRoutineTelemetry(_CompactEventBase):
    """The result document never rides the per-call INFO event."""

    def test_called_event_omits_the_result_document(self):
        ctx = self._context_for("compact.family.op", _ok_handler)
        self.assertNotIn("result", ctx)
        self.assertEqual(ctx["result_byte_count"], len(b'{"status":"ok"}'))
        self.assertEqual(len(ctx["result_checksum"]), 64)

    def test_event_size_is_independent_of_result_size(self):
        small = self._context_for("compact.small.op", _ok_handler)
        small_bytes = len(json.dumps(small, sort_keys=True))
        self.tearDown()
        self.setUp()
        big = self._context_for("compact.big.op", _big_result_handler)
        big_bytes = len(json.dumps(big, sort_keys=True))

        # The handler's result grew by more than 19,000 characters; the
        # event it produced grew only by the id-length difference.
        self.assertGreater(big["result_byte_count"], 19_000)
        self.assertLess(abs(big_bytes - small_bytes), 64)
        self.assertLess(big_bytes, 1_200)


class TestFailureDetailsAreBoundedAndActionable(_CompactEventBase):
    """A failed call carries a code, a clipped message, and a jsonpath."""

    def test_failure_context_is_clipped_and_marked(self):
        ctx = self._context_for("compact.fail.op", _failing_handler)
        self.assertEqual(ctx["verification_status"], "failed")
        self.assertEqual(ctx["error_code"], "claim_required")
        self.assertEqual(len(ctx["error_message"]), FAILURE_TEXT_MAX_CHARS)
        self.assertTrue(ctx["error_message_clipped"])
        self.assertEqual(ctx["error_jsonpath"], "$.payload.item_id")
        # recovery_hint is the constant field-note footer — per-call bytes
        # that say nothing about this call.
        self.assertNotIn("recovery_hint", ctx)
        self.assertNotIn("error_recovery_hint", ctx)

    def test_successful_call_carries_no_error_keys(self):
        ctx = self._context_for("compact.ok.op", _ok_handler)
        self.assertFalse([k for k in ctx if k.startswith("error_")])

    def test_degraded_warning_detail_is_clipped(self):
        register(
            "compact.warn.op", _long_warning_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        dispatch(_make_request("compact.warn.op"))
        calls = events_module.emit_event.calls  # type: ignore[attr-defined]
        degraded = [c for c in calls
                    if c["args"] and c["args"][0] == "DispatcherDownstreamDegraded"]
        self.assertEqual(len(degraded), 1)
        warning = degraded[0]["kwargs"]["context"]["warnings"][0]
        self.assertEqual(len(warning["detail"]), FAILURE_TEXT_MAX_CHARS)
        self.assertTrue(warning["detail_clipped"])

    def test_permission_denial_message_is_clipped(self):
        register(
            "compact.denied.op", _ok_handler, _Req, _Resp, **_stable_kwargs(),
        )
        from yoke_core.domain.yoke_function_registry import lookup

        emit_permission_denied(
            _make_request("compact.denied.op"),
            lookup("compact.denied.op"),
            permission_key="items.write",
            project="yoke",
            message="M" * (FAILURE_TEXT_MAX_CHARS + 1_500),
        )
        calls = events_module.emit_event.calls  # type: ignore[attr-defined]
        denied = [c for c in calls
                  if c["args"] and c["args"][0] == "YokeFunctionPermissionDenied"]
        self.assertEqual(len(denied), 1)
        message = denied[0]["kwargs"]["context"]["message"]
        self.assertEqual(len(message), FAILURE_TEXT_MAX_CHARS)


class TestReplayLedgerSurvivesTelemetryFailure(_DispatcherTestBase):
    """Disposable telemetry must never cost the operational replay row."""

    def test_ledger_is_written_when_emission_raises(self):
        recorded: list[tuple] = []
        register(
            "compact.ledger.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(side_effects=["db_write"]),
        )

        def _raising_emit(*_args: Any, **_kwargs: Any) -> Any:
            raise RetiredEventNameError("YokeFunctionCalled is retired")

        with patch.object(events_module, "emit_event", _raising_emit), \
                patch.object(
                    events_module, "record_call",
                    lambda *a, **k: recorded.append((a, k)) or True):
            with self.assertRaises(RetiredEventNameError):
                dispatch(_make_request("compact.ledger.op", request_id="req-1"))

        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0][0][0], "req-1")
        self.assertEqual(recorded[0][0][2], {"status": "ok"})

    def test_ledger_still_carries_the_full_result(self):
        recorded: list[tuple] = []
        register(
            "compact.ledgerbig.op", _big_result_handler, _Req, _Resp,
            **_stable_kwargs(side_effects=["db_write"]),
        )
        with patch.object(
                events_module, "record_call",
                lambda *a, **k: recorded.append((a, k)) or True):
            resp = dispatch(
                _make_request("compact.ledgerbig.op", request_id="req-2")
            )

        self.assertTrue(resp.success)
        self.assertEqual(resp.result, _BIG_RESULT)
        self.assertEqual(recorded[0][0][2], _BIG_RESULT)
        self.assertNotIn("result", self._called_context_from(events_module))

    @staticmethod
    def _called_context_from(module: Any) -> Dict[str, Any]:
        calls = module.emit_event.calls  # type: ignore[attr-defined]
        called = [c for c in calls
                  if c["args"] and c["args"][0] == "YokeFunctionCalled"]
        return called[-1]["kwargs"]["context"]


class TestIdempotentReplayIsUnchanged(_DispatcherTestBase):
    """A real ledger round-trip still replays the full cached result.

    The first dispatch's ledger arguments become the replay lookup's
    return value, so this exercises the same identity checks production
    runs (function, actor, authorization scope, payload checksum) rather
    than asserting against a hand-built tuple that cannot drift with them.
    """

    def test_replay_returns_the_full_cached_result(self):
        ledgered: list[tuple] = []
        register(
            "compact.replay.op", _big_result_handler, _Req, _Resp,
            **_stable_kwargs(side_effects=["db_write"]),
        )
        with patch.object(
                events_module, "record_call",
                lambda *a, **k: ledgered.append((a, k)) or True):
            first = dispatch(
                _make_request("compact.replay.op", request_id="req-3")
            )
        self.assertTrue(first.success)

        args, kwargs = ledgered[0]
        row = (
            args[2], args[1], kwargs["actor_id"],
            kwargs["authorization_scope"], kwargs["payload_checksum"],
        )
        with patch.object(
                dispatch_module, "_idempotency_lookup", lambda _rid: row):
            replayed = dispatch(
                _make_request("compact.replay.op", request_id="req-3")
            )

        self.assertTrue(replayed.success)
        self.assertEqual(replayed.result, _BIG_RESULT)
        names = events_module.emit_event.names()  # type: ignore[attr-defined]
        self.assertIn("DispatcherIdempotencyReplay", names)


if __name__ == "__main__":  # pragma: no cover - direct invocation
    unittest.main()
