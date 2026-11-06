"""Dispatcher integration coverage for the actor-identity binding layer.

Asserts the transport-symmetric rules end-to-end: the explicit payload
session binds (operator-debug override, recorded in dispatcher event
context with the divergent ambient), a session-less mutating call is
rejected with ``actor_session_missing`` framed for the caller its
process tree names — the infrastructure gap inside a harness, the
supported path in a plain terminal — and calls whose bound session has
no ``harness_sessions`` row carry
``provenance_unverified`` on every dispatcher event. Helper-level tests
live in the sibling module :mod:`test_yoke_function_actor_identity`.
"""

from __future__ import annotations

from runtime.api.domain.yoke_function_actor_identity_dispatch_test_support import (
    _IntegrationBase as _IntegrationBase,
    _Recorder as _Recorder,
    _Req as _Req,
    _Resp as _Resp,
    _make_request as _make_request,
    _ok_handler as _ok_handler,
    _warning_handler as _warning_handler,
)


import unittest
from unittest.mock import patch


from yoke_core.domain.yoke_function_actor_identity import ActorLookup
from yoke_core.domain.yoke_function_dispatch import dispatch


class TestDispatcherMutatingIdentity(_IntegrationBase):
    """Explicit-session override + strict no-session denial, end to end."""

    def test_divergent_payload_session_binds_and_flags_override(self):
        self._register("intg.mut.op", side_effects=["rows_insert"])

        with patch.dict(
            "os.environ",
            {
                "YOKE_SESSION_ID": "ambient-real",
            },
            clear=False,
        ):
            resp = dispatch(
                _make_request(
                    function="intg.mut.op",
                    payload_session="explicit-debug",
                )
            )

        self.assertTrue(resp.success)
        events = self._called_events()
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt["kwargs"]["session_id"], "explicit-debug")
        ctx = evt["kwargs"]["context"]
        self.assertIs(ctx["session_override"], True)
        self.assertEqual(ctx["ambient_session_id"], "ambient-real")

    def _blocked_message(self, function_id: str, harness_family: str) -> str:
        """Dispatch a session-less mutating call under a pinned process tree."""
        self._register(function_id, side_effects=["rows_insert"])
        with patch(
            "yoke_core.domain.session_ambient_identity.nearest_harness_family",
            return_value=harness_family,
        ):
            resp = dispatch(
                _make_request(function=function_id, payload_session=""),
                ambient_session_id="",
            )
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "actor_session_missing")
        self.assertNotIn("YOKE_SESSION_ID", resp.error.message)
        self.assertEqual(self._called_events(), [])
        return resp.error.message

    def test_missing_everything_blocks_mutating_with_reframed_message(self):
        message = self._blocked_message("intg.mut.miss", "claude")
        self.assertIn("infrastructure gap", message)

    def test_missing_everything_outside_a_harness_names_the_terminal_path(self):
        message = self._blocked_message("intg.mut.term", "")
        self.assertIn("harness session", message)
        self.assertNotIn("field-note", message)

    def test_session_optional_mutating_runs_and_audits_without_session(self):
        # Bootstrap/config functions (project install / refresh / onboard,
        # deployment-flow reconciliation) declare ambient_session_required=
        # False so a plain terminal with no harness session can materialize
        # project config. The call runs to completion AND is still recorded
        # via YokeFunctionCalled — session-less, not audit-less.
        self._register(
            "intg.mut.optional",
            side_effects=["rows_insert"],
            ambient_session_required=False,
        )

        resp = dispatch(
            _make_request(function="intg.mut.optional", payload_session=""),
            ambient_session_id="",
        )

        self.assertTrue(resp.success)
        events = self._called_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kwargs"]["session_id"], "")
        self.assertEqual(events[0]["kwargs"]["auth_context"].actor_id, 42)

    def test_unregistered_session_mutating_binds_the_operating_actor(self):
        self._register("intg.mut.unregistered", side_effects=["rows_insert"])
        self.resolver_lookup = ActorLookup(actor_id=None, session_found=False)
        resp = dispatch(
            _make_request(function="intg.mut.unregistered", payload_session="s-x"),
            ambient_session_id="s-x",
        )
        self.assertTrue(resp.success)
        self.assertEqual(self._called_events()[0]["kwargs"]["auth_context"].actor_id, 42)

    def test_mutating_call_with_no_resolvable_actor_refuses_actor_required(self):
        self._register("intg.mut.noactor", side_effects=["rows_insert"])
        self.operating_actor = None
        resp = dispatch(
            _make_request(function="intg.mut.noactor", payload_session="s-y"),
            ambient_session_id="s-y",
        )
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "actor_required")
        self.assertIn("yoke setup", resp.error.message)
        self.assertEqual(self._called_events(), [])

    def test_match_lets_handler_run_without_identity_context(self):
        self._register("intg.mut.match", side_effects=["rows_insert"])

        with patch.dict(
            "os.environ",
            {
                "YOKE_SESSION_ID": "match-session",
            },
            clear=False,
        ):
            resp = dispatch(
                _make_request(
                    function="intg.mut.match",
                    payload_session="match-session",
                )
            )

        self.assertTrue(resp.success)
        ctx = self._called_events()[0]["kwargs"]["context"]
        self.assertNotIn("session_override", ctx)
        self.assertNotIn("ambient_session_id", ctx)
        self.assertNotIn("provenance_unverified", ctx)


class TestDispatcherReadOnlyAttribution(_IntegrationBase):
    """Read-only calls bind by the same payload-first rule and record it."""

    def test_read_only_divergence_records_override_and_ambient(self):
        self._register("intg.ro.op")

        resp = dispatch(
            _make_request(
                function="intg.ro.op",
                payload_session="payload-shaped",
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
                function="intg.ro.matched",
                payload_session="same-session",
            ),
            ambient_session_id="same-session",
        )

        self.assertTrue(resp.success)
        evt = self._called_events()[0]
        ctx = evt["kwargs"]["context"]
        self.assertNotIn("session_override", ctx)
        self.assertNotIn("ambient_session_id", ctx)
        self.assertEqual(evt["kwargs"]["session_id"], "same-session")


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()
