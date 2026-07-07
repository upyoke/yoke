"""Server-side actor_id resolution coverage for the identity binder.

Tests :func:`yoke_core.domain.yoke_function_actor_identity.bind_actor_identity`
along the ``actor_id`` axis: payload-empty / payload-supplied combined
with resolver-returns-value / resolver-returns-None, for both mutating
and read-only registry entries. Session-id binding coverage lives in
sibling :mod:`test_yoke_function_actor_identity`.
"""

from __future__ import annotations

import unittest
from typing import Optional

from pydantic import BaseModel

from yoke_core.domain.yoke_function_actor_identity import (
    ActorLookup,
    bind_actor_identity,
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
) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=_ok_handler,
        request_model=_Req,
        response_model=_Resp,
        stability="stable",
        owner_module="yoke_core.domain.test_actor_id_resolution",
        target_kinds=("item",),
        side_effects=tuple(side_effects),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
        claim_required_kind=claim_required_kind,
    )


def _make_request(
    *,
    payload_session: str = "sess-1",
    payload_actor_id: Optional[str] = "op",
    item_id: int = 7,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="test.family.op",
        actor=ActorContext(actor_id=payload_actor_id, session_id=payload_session),
        target=TargetRef(kind="item", item_id=item_id),
    )


def _fixed_resolver(actor_id: Optional[str], session_found: Optional[bool] = True):
    """Test resolver that returns ``actor_id`` regardless of session_id."""

    def resolve(_session_id: str) -> ActorLookup:
        return ActorLookup(actor_id=actor_id, session_found=session_found)

    return resolve


class TestActorIdResolution(unittest.TestCase):
    """AC-2/AC-3/AC-4/AC-5/AC-13: server-side actor_id resolution."""

    def _mutating_entry(self):
        return _make_entry(side_effects=("rows_insert",))

    def test_ac2_omitted_actor_id_resolves_from_session(self):
        entry = self._mutating_entry()
        request = _make_request(payload_actor_id=None)
        result = bind_actor_identity(
            entry, request,
            ambient_session_id="sess-1",
            actor_id_resolver=_fixed_resolver("resolved-actor-99"),
        )
        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(
            result.bound_request.actor.actor_id, "resolved-actor-99"
        )
        self.assertEqual(result.bound_request.actor.session_id, "sess-1")

    def test_ac4_supplied_matching_actor_id_is_no_op(self):
        entry = self._mutating_entry()
        request = _make_request(payload_actor_id="op-7")
        result = bind_actor_identity(
            entry, request,
            ambient_session_id="sess-1",
            actor_id_resolver=_fixed_resolver("op-7"),
        )
        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(result.bound_request.actor.actor_id, "op-7")

    def test_ac3_supplied_mismatched_actor_id_denies(self):
        entry = self._mutating_entry()
        request = _make_request(payload_actor_id="op-claimed")
        result = bind_actor_identity(
            entry, request,
            ambient_session_id="sess-1",
            actor_id_resolver=_fixed_resolver("op-real"),
        )
        self.assertIsNone(result.bound_request)
        assert result.error is not None
        self.assertEqual(result.error.error.code, "actor_id_mismatch")
        self.assertIn("op-claimed", result.error.error.message)
        self.assertIn("op-real", result.error.error.message)

    def test_ac5_omitted_actor_id_unregistered_session_leaves_none(self):
        # Per AC-5 + AC-13: missing resolution is NOT a new failure
        # mode. Binder leaves actor.actor_id as None; downstream gates
        # reject unregistered sessions naturally, and the positive
        # no-row finding rides out for provenance marking.
        entry = self._mutating_entry()
        request = _make_request(payload_actor_id=None)
        result = bind_actor_identity(
            entry, request,
            ambient_session_id="sess-1",
            actor_id_resolver=_fixed_resolver(None, session_found=False),
        )
        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertIsNone(result.bound_request.actor.actor_id)
        self.assertIs(result.session_registered, False)

    def test_ac13_blank_actor_id_null_resolver_passes_through(self):
        entry = self._mutating_entry()
        request = _make_request(payload_actor_id="")
        result = bind_actor_identity(
            entry, request,
            ambient_session_id="sess-1",
            actor_id_resolver=_fixed_resolver(None),
        )
        self.assertIsNone(result.error)
        assert result.bound_request is not None
        # Blank-string payload stays as-is when nothing resolves.
        self.assertIn(result.bound_request.actor.actor_id, ("", None))

    def test_ac13_blank_actor_id_resolves_when_session_has_actor(self):
        entry = self._mutating_entry()
        request = _make_request(payload_actor_id="")
        result = bind_actor_identity(
            entry, request,
            ambient_session_id="sess-1",
            actor_id_resolver=_fixed_resolver("resolved-actor"),
        )
        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(
            result.bound_request.actor.actor_id, "resolved-actor"
        )

    def test_read_only_missing_actor_id_passes_through(self):
        entry = _make_entry()
        request = _make_request(payload_actor_id=None)
        result = bind_actor_identity(
            entry, request,
            ambient_session_id="sess-1",
            actor_id_resolver=_fixed_resolver(None),
        )
        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertIsNone(result.bound_request.actor.actor_id)

    def test_read_only_mismatched_actor_id_passes_through(self):
        entry = _make_entry()
        request = _make_request(payload_actor_id="op-payload")
        result = bind_actor_identity(
            entry, request,
            ambient_session_id="sess-1",
            actor_id_resolver=_fixed_resolver("op-resolved"),
        )
        self.assertIsNone(result.error)
        assert result.bound_request is not None
        self.assertEqual(
            result.bound_request.actor.actor_id, "op-payload"
        )


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()
