"""Tests for the Yoke function-call dispatcher.

Idempotency (replay/collision/ledger) coverage lives in the sibling
``test_yoke_function_dispatch_idempotency.py`` suite.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

from pydantic import BaseModel

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.observe_anomaly import detect_anomalies
from yoke_core.domain.observe_event_emission import build_envelope, insert_event
from yoke_core.domain.observe_parsing import parse_hook_event
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionWarning,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)
from runtime.api.observe_full_test_helpers import make_events_db_file


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _stable_kwargs(**overrides):
    base = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_dispatch",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["FakeEvent"],
        "guardrails": [],
        "adapter_status": "live",
    }
    base.update(overrides)
    return base


def _ok_handler(_request):
    return HandlerOutcome(result_payload={"status": "ok"}, primary_success=True)


def _warning_handler(_request):
    return HandlerOutcome(
        result_payload={"status": "ok"},
        primary_success=True,
        warnings=[
            FunctionWarning(
                code="github_sync_degraded",
                step="github_sync",
                detail="rate-limited",
            )
        ],
    )


def _make_request(
    function: str,
    *,
    item_id: int = 42,
    session_id: str = "s-1",
    request_id: Optional[str] = None,
    kind: str = "item",
    epic_id: Optional[int] = None,
    task_num: Optional[int] = None,
    claim_id: Optional[int] = None,
) -> FunctionCallRequest:
    target = TargetRef(
        kind=kind,
        item_id=item_id if kind == "item" else None,
        epic_id=epic_id,
        task_num=task_num,
        claim_id=claim_id,
    )
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id=session_id),
        target=target,
        request_id=request_id,
    )


# A capturing event recorder used everywhere to silence and inspect calls.
class _EventRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, "kwargs": kwargs})

    def names(self) -> list[str]:
        return [c["args"][0] if c["args"] else c["kwargs"].get("event_name", "")
                for c in self.calls]


class _DispatcherTestBase(unittest.TestCase):
    """Shared scaffolding: silence emit_event and clear the registry."""

    def setUp(self) -> None:
        reset_registry_for_tests()
        # Silence every event emission path + the idempotency-ledger
        # write/read so unit dispatches never touch the shared test DB.
        self._patchers = [
            patch.object(events_module, "emit_event", _EventRecorder()),
            patch.object(events_module, "record_call", lambda *_a, **_k: True),
            patch.object(dispatch_module, "_idempotency_lookup", lambda *_a, **_k: None),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()


class TestEnvelopeValidation(_DispatcherTestBase):
    """AC-1.6: envelope-shape failure -> envelope_invalid."""

    def test_malformed_payload(self):
        resp = dispatch({"function": "foo.bar.baz"})
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "envelope_invalid")

    def test_invalid_function_field_type(self):
        resp = dispatch({
            "function": 123,
            "actor": {"actor_id": "x", "session_id": "y"},
            "target": {"kind": "item", "item_id": 1},
        })
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "envelope_invalid")

    def test_malformed_envelope_never_reflects_payload_credentials(self):
        secret = "github-user-token-must-not-be-reflected"
        resp = dispatch({
            "function": "projects.github_binding.bind",
            "actor": {"actor_id": "operator"},
            "target": {"kind": "global"},
            "payload": {"github_user_access_token": secret},
        })

        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "envelope_invalid")
        self.assertIn("actor.session_id", resp.error.message)
        self.assertNotIn(secret, resp.model_dump_json())


class TestFunctionNotRegistered(_DispatcherTestBase):
    """AC-1.7: unknown id -> function_not_registered."""

    def test_unknown_function_returns_not_registered(self):
        resp = dispatch(_make_request("unregistered.family.op"))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "function_not_registered")


class TestHappyPath(_DispatcherTestBase):
    """Baseline: registered handler executes; response has result + no error."""

    def test_handler_runs(self):
        register(
            "happy.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        resp = dispatch(_make_request("happy.family.op"))
        self.assertTrue(resp.success)
        self.assertEqual(resp.result, {"status": "ok"})
        self.assertIsNone(resp.error)

    def test_partial_state_warnings_path(self):
        register(
            "warning.family.op", _warning_handler, _Req, _Resp,
            **_stable_kwargs(),
        )
        resp = dispatch(_make_request("warning.family.op"))
        self.assertTrue(resp.success)
        self.assertEqual(len(resp.warnings), 1)
        self.assertEqual(resp.warnings[0].code, "github_sync_degraded")
        # The dispatcher emitted DispatcherDownstreamDegraded + YokeFunctionCalled.
        names = events_module.emit_event.names()  # type: ignore[attr-defined]
        self.assertIn("DispatcherDownstreamDegraded", names)
        self.assertIn("YokeFunctionCalled", names)


class TestEventEmission(_DispatcherTestBase):
    """AC-1.11: YokeFunctionCalled per call carries the required fields."""

    def test_called_event_envelope(self):
        register(
            "evt.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(guardrails=["empty_body_guard"]),
        )
        dispatch(_make_request("evt.family.op"))
        calls = events_module.emit_event.calls  # type: ignore[attr-defined]
        called_events = [c for c in calls if c["args"] and c["args"][0] == "YokeFunctionCalled"]
        self.assertEqual(len(called_events), 1)
        ctx = called_events[0]["kwargs"]["context"]
        for key in (
            "function", "version", "target", "payload_byte_count",
            "payload_checksum", "guardrail_outcomes",
            "verification_status", "sync_status", "event_ids",
            "result_byte_count", "result_checksum",
        ):
            self.assertIn(key, ctx)
        self.assertEqual(ctx["guardrail_outcomes"], ["empty_body_guard"])
        self.assertEqual(ctx["verification_status"], "ok")
        self.assertEqual(ctx["sync_status"], "ok")


def _run_observe(payload: Dict[str, Any], db_path: str) -> tuple:
    """Drive parse -> anomalies -> emit; return (item_id, anomaly_flags, attribution_source)."""
    rec = parse_hook_event(payload, hook_event="PostToolUse", db_path=db_path)
    assert rec is not None
    detect_anomalies(rec)
    envelope = build_envelope(rec)
    conn = connect_test_db(db_path)
    try:
        insert_event(conn, envelope)
        row = conn.execute(
            "SELECT item_id, anomaly_flags FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return row[0], row[1] or "", envelope.get("attribution_source")


def _bash_payload(command: str, tool_use_id: str) -> Dict[str, Any]:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"content": "Exit code 0"},
        "session_id": "test-session",
        "tool_use_id": tool_use_id,
    }


class TestDispatcherWrapperAttribution(unittest.TestCase):
    """AC-5/6/7: wrapping HarnessToolCallCompleted rows carry resolved item_id
    when the Bash command is a function-call dispatcher invocation."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="dispatch-attribution-")
        self.db_context = make_events_db_file(Path(self.tmpdir))
        self.db_path = self.db_context.__enter__()

    def tearDown(self) -> None:
        try:
            self.db_context.__exit__(None, None, None)
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_service_client_adapter_resolves_item_id(self):
        # service_client db-claim-amend --item YOK-1761 path.
        cmd = (
            "python3 -m yoke_core.api.service_client db-claim-amend "
            "--item YOK-1761 --reason test --state none"
        )
        item_id, flags, _src = _run_observe(_bash_payload(cmd, "tu-svc"), self.db_path)
        self.assertEqual(item_id, "1761")
        self.assertNotIn("unattributed", flags)

    def test_curl_envelope_post_resolves_item_id(self):
        # Curl --data-binary @envelope.json post.
        envelope_path = os.path.join(self.tmpdir, "envelope.json")
        with open(envelope_path, "w") as handle:
            json.dump({"target": {"kind": "item", "item_id": 1761}}, handle)
        cmd = (
            f"curl -sS -X POST http://localhost:8000/v1/functions/call "
            f"--data-binary @{envelope_path}"
        )
        item_id, flags, src = _run_observe(_bash_payload(cmd, "tu-curl"), self.db_path)
        self.assertEqual(item_id, "1761")
        self.assertEqual(src, "explicit_function_call_envelope")
        self.assertNotIn("unattributed", flags)

    def test_plain_bash_still_flagged_unattributed(self):
        # Plain Bash with no function-call shape stays unattributed.
        item_id, flags, _src = _run_observe(
            _bash_payload("ls -la /tmp", "tu-plain"), self.db_path
        )
        self.assertIsNone(item_id)
        self.assertIn("unattributed", flags)


if __name__ == "__main__":
    unittest.main()
