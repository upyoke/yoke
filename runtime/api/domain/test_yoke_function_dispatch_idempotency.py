"""Dispatcher idempotency suite — replay/collision against the ledger.

Two layers:

- ``TestIdempotencyDecision`` pins the ``_handle_idempotency`` response
  shapes (replay envelope, cross-function collision) with a patched
  lookup, independent of storage.
- ``TestLedgerBackedIdempotency`` exercises the real store end to end:
  ``emit_called`` writes one ``function_call_ledger`` row per dispatched
  ``request_id`` and ``_idempotency_lookup`` replays the stored result
  bit-for-bit without re-running the handler.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

from pydantic import BaseModel

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _stable_kwargs(**overrides):
    base = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_dispatch_idempotency",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["FakeEvent"],
        "guardrails": [],
        "adapter_status": "live",
    }
    base.update(overrides)
    return base


def _make_request(
    function: str,
    *,
    request_id: Optional[str] = None,
    session_id: str = "s-1",
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id=session_id),
        target=TargetRef(kind="item", item_id=42),
        request_id=request_id,
    )


class _EventRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, "kwargs": kwargs})

    def names(self) -> list[str]:
        return [c["args"][0] if c["args"] else c["kwargs"].get("event_name", "")
                for c in self.calls]


class TestIdempotencyDecision(unittest.TestCase):
    """Replay + collision response shapes with a patched lookup."""

    def setUp(self) -> None:
        reset_registry_for_tests()
        self._patchers = [
            patch.object(events_module, "emit_event", _EventRecorder()),
            patch.object(events_module, "record_call", lambda *_a, **_k: True),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()

    def test_replay_returns_stored_result(self):
        register(
            "idem.family.op",
            lambda _r: HandlerOutcome(result_payload={"status": "ok"}, primary_success=True),
            _Req, _Resp, **_stable_kwargs(),
        )
        stored = ({"replayed": True}, "idem.family.op")
        with patch.object(
            dispatch_module, "_idempotency_lookup", return_value=stored
        ):
            resp = dispatch(_make_request("idem.family.op", request_id="r-1"))
        self.assertTrue(resp.success)
        self.assertEqual(resp.result, {"replayed": True})
        names = events_module.emit_event.names()  # type: ignore[attr-defined]
        self.assertIn("DispatcherIdempotencyReplay", names)

    def test_collision_across_families_returns_error(self):
        for fid in ("first.family.op", "second.family.op"):
            register(
                fid,
                lambda _r: HandlerOutcome(result_payload={"status": "ok"}, primary_success=True),
                _Req, _Resp, **_stable_kwargs(),
            )
        stored = ({"old": True}, "first.family.op")
        with patch.object(
            dispatch_module, "_idempotency_lookup", return_value=stored
        ):
            resp = dispatch(_make_request("second.family.op", request_id="r-1"))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "idempotency_key_collision")


class TestLedgerBackedIdempotency(unittest.TestCase):
    """End-to-end replay against a real function_call_ledger."""

    NESTED_RESULT = {
        "status": "ok",
        "nested": {"a": [1, 2, {"b": "c"}], "flag": True},
        "unicode": "café ↯",
    }

    def setUp(self) -> None:
        reset_registry_for_tests()
        self.tmpdir = tempfile.mkdtemp(prefix="fcl-dispatch-")
        self._db_ctx = init_test_db(Path(self.tmpdir))
        self.db_path = self._db_ctx.__enter__()
        # Silence telemetry emission; the ledger write stays real.
        self._emit_patch = patch.object(
            events_module, "emit_event", _EventRecorder()
        )
        self._emit_patch.start()
        self.handler_calls: list[str] = []

        def _counting_handler(_request):
            self.handler_calls.append(_request.function)
            return HandlerOutcome(
                result_payload=dict(self.NESTED_RESULT), primary_success=True,
            )

        def _failing_handler(_request):
            self.handler_calls.append(_request.function)
            return HandlerOutcome(
                result_payload={"why": "boom"}, primary_success=False,
            )

        # Ledger semantics apply to side-effecting entries; the read-shape
        # registration pins the skip.
        register(
            "ledger.family.op", _counting_handler, _Req, _Resp,
            **_stable_kwargs(side_effects=["items row"]),
        )
        register(
            "ledger.other.op", _counting_handler, _Req, _Resp,
            **_stable_kwargs(side_effects=["items row"]),
        )
        register(
            "ledger.failing.op", _failing_handler, _Req, _Resp,
            **_stable_kwargs(side_effects=["items row"]),
        )
        register(
            "ledger.read.op", _counting_handler, _Req, _Resp,
            **_stable_kwargs(),
        )

    def tearDown(self) -> None:
        self._emit_patch.stop()
        self._db_ctx.__exit__(None, None, None)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        reset_registry_for_tests()

    def _ledger_rows(self) -> dict:
        conn = connect_test_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT request_id, function_id, result "
                "FROM function_call_ledger"
            ).fetchall()
        finally:
            conn.close()
        return {row[0]: (row[1], row[2]) for row in rows}

    def test_ledger_row_written_per_call(self):
        resp = dispatch(_make_request("ledger.family.op", request_id="r-row"))
        self.assertTrue(resp.success)
        rows = self._ledger_rows()
        self.assertEqual(set(rows), {"r-row"})
        function_id, raw = rows["r-row"]
        self.assertEqual(function_id, "ledger.family.op")
        self.assertEqual(json.loads(raw), self.NESTED_RESULT)

    def test_replay_returns_stored_result_without_rerun(self):
        first = dispatch(_make_request("ledger.family.op", request_id="r-2"))
        second = dispatch(_make_request("ledger.family.op", request_id="r-2"))
        self.assertEqual(self.handler_calls, ["ledger.family.op"])
        self.assertTrue(second.success)
        self.assertEqual(second.result, first.result)
        self.assertEqual(second.result, self.NESTED_RESULT)
        names = events_module.emit_event.names()  # type: ignore[attr-defined]
        self.assertIn("DispatcherIdempotencyReplay", names)

    def test_cross_function_collision_preserved(self):
        dispatch(_make_request("ledger.family.op", request_id="r-x"))
        resp = dispatch(_make_request("ledger.other.op", request_id="r-x"))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "idempotency_key_collision")
        self.assertIn("ledger.family.op", resp.error.message)
        self.assertIn("ledger.other.op", resp.error.message)
        # The collision did not run the second handler or overwrite the row.
        self.assertEqual(self.handler_calls, ["ledger.family.op"])
        self.assertEqual(
            self._ledger_rows()["r-x"][0], "ledger.family.op",
        )

    def test_distinct_request_ids_dispatch_fresh(self):
        dispatch(_make_request("ledger.family.op", request_id="r-a"))
        dispatch(_make_request("ledger.family.op", request_id="r-b"))
        self.assertEqual(
            self.handler_calls, ["ledger.family.op", "ledger.family.op"],
        )
        self.assertEqual(set(self._ledger_rows()), {"r-a", "r-b"})

    def test_no_request_id_writes_no_row_and_never_replays(self):
        dispatch(_make_request("ledger.family.op"))
        dispatch(_make_request("ledger.family.op"))
        self.assertEqual(len(self.handler_calls), 2)
        self.assertEqual(self._ledger_rows(), {})

    def test_read_shape_entry_never_ledgered(self):
        """side_effects=[] entries skip the ledger even with a request_id —
        reads are naturally idempotent and their results can be large."""
        dispatch(_make_request("ledger.read.op", request_id="r-read"))
        dispatch(_make_request("ledger.read.op", request_id="r-read"))
        self.assertEqual(len(self.handler_calls), 2)
        self.assertEqual(self._ledger_rows(), {})

    def test_failed_outcome_recorded_and_replayed(self):
        """Parity with the retired envelope scan: failed calls replay too."""
        first = dispatch(_make_request("ledger.failing.op", request_id="r-f"))
        self.assertFalse(first.success)
        second = dispatch(_make_request("ledger.failing.op", request_id="r-f"))
        self.assertEqual(self.handler_calls, ["ledger.failing.op"])
        self.assertTrue(second.success)
        self.assertEqual(second.result, {"why": "boom"})


if __name__ == "__main__":
    unittest.main()
