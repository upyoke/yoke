"""Dispatcher integration coverage for the actor-identity binding layer.

Asserts the transport-symmetric rules end-to-end: the explicit payload
session binds (operator-debug override, recorded in dispatcher event
context with the divergent ambient), a session-less mutating call is
rejected with the infrastructure-framed ``actor_session_missing``, and
calls whose bound session has no ``harness_sessions`` row carry
``provenance_unverified`` on every dispatcher event. Helper-level tests
live in the sibling module :mod:`test_yoke_function_actor_identity`.
"""

from __future__ import annotations

import unittest
from typing import Optional
from unittest.mock import patch

from pydantic import BaseModel

from yoke_core.domain import yoke_function_actor_identity as identity_module
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.yoke_function_actor_identity import ActorLookup
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


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _ok_handler(_request):
    return HandlerOutcome(result_payload={"ok": True}, primary_success=True)


def _warning_handler(_request):
    return HandlerOutcome(
        result_payload={"ok": True},
        primary_success=True,
        warnings=[
            FunctionWarning(code="downstream", step="x", detail="fail")
        ],
    )


def _make_request(
    *,
    function: str = "test.family.op",
    payload_session: str = "payload-s",
    item_id: int = 7,
    request_id: Optional[str] = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id=payload_session),
        target=TargetRef(kind="item", item_id=item_id),
        request_id=request_id,
    )


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append({"args": a, "kwargs": kw})

    def names(self):
        return [
            c["args"][0] if c["args"] else c["kwargs"].get("event_name")
            for c in self.calls
        ]


class _IntegrationBase(unittest.TestCase):
    resolver_lookup = ActorLookup(actor_id=None, session_found=True)

    def setUp(self):
        reset_registry_for_tests()
        self._recorder = _Recorder()
        self._patchers = [
            patch.object(events_module, "emit_event", self._recorder),
            patch.object(
                dispatch_module, "_idempotency_lookup",
                lambda *_a, **_k: None,
            ),
            patch.object(
                identity_module, "_default_actor_id_resolver",
                lambda _sid: self.resolver_lookup,
            ),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()

    def _register(self, function_id, handler=_ok_handler, side_effects=()):
        register(
            function_id, handler, _Req, _Resp,
            stability="stable",
            owner_module="yoke_core.domain.test_actor_identity",
            target_kinds=["item"],
            side_effects=list(side_effects),
            emitted_event_names=[],
            guardrails=[],
            adapter_status="live",
        )

    def _called_events(self, name="YokeFunctionCalled"):
        return [
            c for c in self._recorder.calls
            if c["args"] and c["args"][0] == name
        ]


class TestDispatcherMutatingIdentity(_IntegrationBase):
    """Explicit-session override + strict no-session denial, end to end."""

    def test_divergent_payload_session_binds_and_flags_override(self):
        self._register("intg.mut.op", side_effects=["rows_insert"])

        with patch.dict("os.environ", {
            "YOKE_SESSION_ID": "ambient-real",
        }, clear=False):
            resp = dispatch(_make_request(
                function="intg.mut.op",
                payload_session="explicit-debug",
            ))

        self.assertTrue(resp.success)
        events = self._called_events()
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt["kwargs"]["session_id"], "explicit-debug")
        ctx = evt["kwargs"]["context"]
        self.assertIs(ctx["session_override"], True)
        self.assertEqual(ctx["ambient_session_id"], "ambient-real")

    def test_missing_everything_blocks_mutating_with_reframed_message(self):
        self._register("intg.mut.miss", side_effects=["rows_insert"])

        resp = dispatch(
            _make_request(function="intg.mut.miss", payload_session=""),
            ambient_session_id="",
        )

        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "actor_session_missing")
        self.assertIn("infrastructure gap", resp.error.message)
        self.assertNotIn("YOKE_SESSION_ID", resp.error.message)
        self.assertEqual(self._called_events(), [])

    def test_match_lets_handler_run_without_identity_context(self):
        self._register("intg.mut.match", side_effects=["rows_insert"])

        with patch.dict("os.environ", {
            "YOKE_SESSION_ID": "match-session",
        }, clear=False):
            resp = dispatch(_make_request(
                function="intg.mut.match",
                payload_session="match-session",
            ))

        self.assertTrue(resp.success)
        ctx = self._called_events()[0]["kwargs"]["context"]
        self.assertNotIn("session_override", ctx)
        self.assertNotIn("ambient_session_id", ctx)
        self.assertNotIn("provenance_unverified", ctx)


class TestDispatcherProvenanceMarking(_IntegrationBase):
    """Calls from sessions with no harness_sessions row are marked."""

    resolver_lookup = ActorLookup(actor_id=None, session_found=False)

    def test_unregistered_session_marks_called_event(self):
        self._register("intg.mut.ghost", side_effects=["rows_insert"])

        resp = dispatch(
            _make_request(
                function="intg.mut.ghost", payload_session="ghost-session",
            ),
            ambient_session_id="ghost-session",
        )

        self.assertTrue(resp.success)
        ctx = self._called_events()[0]["kwargs"]["context"]
        self.assertIs(ctx["provenance_unverified"], True)

    def test_unregistered_session_marks_downstream_degraded(self):
        self._register(
            "intg.warn.ghost", handler=_warning_handler,
            side_effects=["rows_insert"],
        )

        resp = dispatch(
            _make_request(
                function="intg.warn.ghost", payload_session="ghost-session",
            ),
            ambient_session_id="ghost-session",
        )

        self.assertTrue(resp.success)
        warn_events = self._called_events("DispatcherDownstreamDegraded")
        self.assertEqual(len(warn_events), 1)
        self.assertIs(
            warn_events[0]["kwargs"]["context"]["provenance_unverified"],
            True,
        )

    def test_unregistered_session_marks_idempotency_replay(self):
        self._register("intg.replay.ghost", side_effects=["rows_insert"])

        stored = ({"replayed": True}, "intg.replay.ghost")
        with patch.object(
            dispatch_module, "_idempotency_lookup", return_value=stored,
        ):
            resp = dispatch(
                _make_request(
                    function="intg.replay.ghost",
                    payload_session="ghost-session",
                    request_id="r-1",
                ),
                ambient_session_id="ghost-session",
            )

        self.assertTrue(resp.success)
        replay_events = self._called_events("DispatcherIdempotencyReplay")
        self.assertEqual(len(replay_events), 1)
        self.assertIs(
            replay_events[0]["kwargs"]["context"]["provenance_unverified"],
            True,
        )


class TestDispatcherReadOnlyAttribution(_IntegrationBase):
    """Read-only calls bind by the same payload-first rule and record it."""

    def test_read_only_divergence_records_override_and_ambient(self):
        self._register("intg.ro.op")

        resp = dispatch(
            _make_request(
                function="intg.ro.op", payload_session="payload-shaped",
            ),
            ambient_session_id="real-caller",
        )

        self.assertTrue(resp.success)
        events = self._called_events()
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt["kwargs"]["session_id"], "payload-shaped")
        ctx = evt["kwargs"]["context"]
        self.assertIs(ctx["session_override"], True)
        self.assertEqual(ctx["ambient_session_id"], "real-caller")

    def test_read_only_match_omits_identity_context(self):
        self._register("intg.ro.matched")

        resp = dispatch(
            _make_request(
                function="intg.ro.matched", payload_session="same-session",
            ),
            ambient_session_id="same-session",
        )

        self.assertTrue(resp.success)
        evt = self._called_events()[0]
        ctx = evt["kwargs"]["context"]
        self.assertNotIn("session_override", ctx)
        self.assertNotIn("ambient_session_id", ctx)
        self.assertEqual(evt["kwargs"]["session_id"], "same-session")


class TestHttpBoundaryAmbient(unittest.TestCase):
    """The https boundary never lets the server's env stand in for the caller."""

    def test_empty_envelope_session_with_empty_ambient_stays_missing(self):
        reset_registry_for_tests()
        recorder = _Recorder()
        with patch.object(events_module, "emit_event", recorder), patch.object(
            identity_module, "_default_actor_id_resolver",
            lambda _sid: ActorLookup(),
        ):
            register(
                "intg.http.op", _ok_handler, _Req, _Resp,
                stability="stable",
                owner_module="yoke_core.domain.test_actor_identity",
                target_kinds=["item"],
                side_effects=["rows_insert"],
                emitted_event_names=[],
                guardrails=[],
                adapter_status="live",
            )
            with patch.dict("os.environ", {
                "YOKE_SESSION_ID": "server-process-session",
            }, clear=False):
                # ambient_session_id="" is what the HTTP route passes when
                # the envelope carries no session: the server env must NOT
                # be consulted as the caller's ambient identity.
                resp = dispatch(
                    _make_request(
                        function="intg.http.op", payload_session="",
                    ),
                    ambient_session_id="",
                )
        reset_registry_for_tests()
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "actor_session_missing")


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()
