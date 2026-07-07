"""Helper-level tests for the ambient-session identity-binding layer.

Focused unit coverage of :func:`bind_actor_identity` against synthetic
registry entries: classifier (read-only vs mutating), the
transport-symmetric bound-session rule (payload wins, ambient fills),
the operator-debug override flag, the reframed ``actor_session_missing``
denial, and the registration finding threading. Dispatcher integration
coverage lives in the sibling module
:mod:`test_yoke_function_actor_identity_dispatch`.
"""

from __future__ import annotations

import unittest
from typing import Optional

from pydantic import BaseModel

from yoke_core.domain.yoke_function_actor_identity import (
    ActorLookup,
    bind_actor_identity,
    is_read_only,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _ok_handler(_request):
    return HandlerOutcome(result_payload={"ok": True}, primary_success=True)


def _make_entry(
    *,
    function_id: str = "test.family.op",
    claim_required_kind: Optional[str] = None,
    side_effects: tuple = (),
    handler=_ok_handler,
    ambient_session_required: bool = True,
) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=handler,
        request_model=_Req,
        response_model=_Resp,
        stability="stable",
        owner_module="yoke_core.domain.test_actor_identity",
        target_kinds=("item",),
        side_effects=tuple(side_effects),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
        claim_required_kind=claim_required_kind,
        ambient_session_required=ambient_session_required,
    )


def _make_request(
    *,
    function: str = "test.family.op",
    payload_session: str = "payload-s",
    payload_actor_id: Optional[str] = "op",
    item_id: int = 7,
    request_id: Optional[str] = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=payload_actor_id, session_id=payload_session),
        target=TargetRef(kind="item", item_id=item_id),
        request_id=request_id,
    )


def _fixed_resolver(actor_id: Optional[str], session_found: Optional[bool] = True):
    """Test resolver that returns a fixed lookup regardless of session_id."""

    def resolve(_session_id: str) -> ActorLookup:
        return ActorLookup(actor_id=actor_id, session_found=session_found)

    return resolve


_PASSTHROUGH = _fixed_resolver(None, session_found=True)


class TestReadOnlyClassifier(unittest.TestCase):
    """Read-only classification is registry-derived."""

    def test_read_only_when_no_claim_no_side_effects(self):
        self.assertTrue(is_read_only(_make_entry()))

    def test_mutating_when_side_effects_present(self):
        self.assertFalse(
            is_read_only(_make_entry(side_effects=("foo_insert",)))
        )

    def test_mutating_when_claim_required(self):
        self.assertFalse(
            is_read_only(_make_entry(claim_required_kind="item"))
        )


class TestMutatingBindings(unittest.TestCase):
    """Mutating gates bind payload-first with the ambient as fill-in."""

    def test_match_returns_unchanged_bound_request(self):
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="abc")
        result = bind_actor_identity(
            entry, request, ambient_session_id="abc",
            actor_id_resolver=_PASSTHROUGH,
        )

        self.assertIsNone(result.error)
        self.assertIs(result.bound_request, request)
        self.assertEqual(result.payload_session_id, "abc")
        self.assertEqual(result.ambient_session_id, "abc")
        self.assertFalse(result.explicit_override)

    def test_divergent_payload_session_is_flagged_override(self):
        """Transport symmetry: the explicit payload session is accepted on
        both transports as the operator-debug override path — bound to the
        payload session, flagged, never silently rejected."""
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="explicit-override")
        result = bind_actor_identity(
            entry, request, ambient_session_id="ambient-resolved",
            actor_id_resolver=_PASSTHROUGH,
        )

        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(
            result.bound_request.actor.session_id, "explicit-override"
        )
        self.assertTrue(result.explicit_override)
        self.assertEqual(result.payload_session_id, "explicit-override")
        self.assertEqual(result.ambient_session_id, "ambient-resolved")

    def test_payload_session_accepted_without_ambient(self):
        """The 12352/12353 shape: explicit session with no ambient resolves
        on the in-process transport exactly as it does over https."""
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="explicit-only")
        result = bind_actor_identity(
            entry, request, ambient_session_id="",
            actor_id_resolver=_PASSTHROUGH,
        )

        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(
            result.bound_request.actor.session_id, "explicit-only"
        )
        self.assertTrue(result.explicit_override)

    def test_no_session_anywhere_returns_actor_session_missing(self):
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="")
        result = bind_actor_identity(
            entry, request, ambient_session_id="",
            actor_id_resolver=_PASSTHROUGH,
        )

        self.assertIsNone(result.bound_request)
        assert result.error is not None
        self.assertEqual(result.error.error.code, "actor_session_missing")
        self.assertEqual(result.payload_session_id, "")
        self.assertEqual(result.ambient_session_id, "")

    def test_missing_message_is_infrastructure_framed_not_env_teaching(self):
        """The denial names the infrastructure gap and the operator-debug
        override; it must not teach env-var self-bootstrap."""
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="")
        result = bind_actor_identity(
            entry, request, ambient_session_id="",
            actor_id_resolver=_PASSTHROUGH,
        )

        assert result.error is not None
        message = result.error.error.message
        self.assertIn("infrastructure gap", message)
        self.assertIn("field-note", message)
        self.assertIn("--session-id", message)
        self.assertIn("Operator-debug", message)
        for env_name in (
            "YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID",
        ):
            self.assertNotIn(env_name, message)
        self.assertNotIn("export", message)

    def test_ambient_fills_when_payload_empty(self):
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="")
        result = bind_actor_identity(
            entry, request, ambient_session_id="ambient-1",
            actor_id_resolver=_PASSTHROUGH,
        )

        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(result.bound_request.actor.session_id, "ambient-1")
        self.assertFalse(result.explicit_override)

    def test_session_optional_side_effect_allows_operator_shell(self):
        entry = _make_entry(
            side_effects=("board_rewrite",),
            ambient_session_required=False,
        )
        request = _make_request(payload_session="")
        result = bind_actor_identity(
            entry, request, ambient_session_id="",
            actor_id_resolver=_PASSTHROUGH,
        )

        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(result.bound_request.actor.session_id, "")

    def test_session_optional_side_effect_binds_payload_first(self):
        entry = _make_entry(
            side_effects=("board_rewrite",),
            ambient_session_required=False,
        )
        request = _make_request(payload_session="payload-side")
        result = bind_actor_identity(
            entry, request, ambient_session_id="ambient-side",
            actor_id_resolver=_PASSTHROUGH,
        )

        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(result.bound_request.actor.session_id, "payload-side")
        self.assertEqual(result.payload_session_id, "payload-side")
        self.assertEqual(result.ambient_session_id, "ambient-side")
        self.assertTrue(result.explicit_override)


class TestRegistrationFinding(unittest.TestCase):
    """The harness_sessions row-existence finding rides out of the binder."""

    def test_registered_session_reports_found(self):
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="abc", payload_actor_id=None)
        result = bind_actor_identity(
            entry, request, ambient_session_id="abc",
            actor_id_resolver=_fixed_resolver("9", session_found=True),
        )
        self.assertIsNone(result.error)
        self.assertIs(result.session_registered, True)

    def test_unregistered_session_reports_not_found(self):
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="ghost", payload_actor_id=None)
        result = bind_actor_identity(
            entry, request, ambient_session_id="ghost",
            actor_id_resolver=_fixed_resolver(None, session_found=False),
        )
        self.assertIsNone(result.error)
        self.assertIs(result.session_registered, False)

    def test_failed_lookup_reports_unknown(self):
        entry = _make_entry(side_effects=("rows_insert",))
        request = _make_request(payload_session="abc", payload_actor_id=None)
        result = bind_actor_identity(
            entry, request, ambient_session_id="abc",
            actor_id_resolver=_fixed_resolver(None, session_found=None),
        )
        self.assertIsNone(result.error)
        self.assertIsNone(result.session_registered)

    def test_no_session_at_all_skips_lookup(self):
        entry = _make_entry()
        request = _make_request(payload_session="")
        result = bind_actor_identity(
            entry, request, ambient_session_id="",
            actor_id_resolver=_fixed_resolver(None, session_found=False),
        )
        self.assertIsNone(result.error)
        self.assertIsNone(result.session_registered)


class TestReadOnlyBindings(unittest.TestCase):
    """Read-only execution binds by the same payload-first rule."""

    def test_match_returns_unchanged_request(self):
        entry = _make_entry()
        request = _make_request(payload_session="x")
        result = bind_actor_identity(
            entry, request, ambient_session_id="x",
            actor_id_resolver=_PASSTHROUGH,
        )
        self.assertIs(result.bound_request, request)

    def test_divergence_binds_payload_and_preserves_ambient(self):
        entry = _make_entry()
        request = _make_request(payload_session="payload-side")
        result = bind_actor_identity(
            entry, request, ambient_session_id="ambient-side",
            actor_id_resolver=_PASSTHROUGH,
        )

        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(
            result.bound_request.actor.session_id, "payload-side"
        )
        self.assertEqual(result.payload_session_id, "payload-side")
        self.assertEqual(result.ambient_session_id, "ambient-side")
        self.assertTrue(result.explicit_override)

    def test_missing_ambient_preserves_payload(self):
        entry = _make_entry()
        request = _make_request(payload_session="payload-side")
        result = bind_actor_identity(
            entry, request, ambient_session_id="",
            actor_id_resolver=_PASSTHROUGH,
        )
        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(
            result.bound_request.actor.session_id, "payload-side"
        )
        self.assertEqual(result.ambient_session_id, "")


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()
