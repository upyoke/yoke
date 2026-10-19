"""A session-less mutating call or viewer-scoped read is attributed.

Item creation resolved the operating actor for itself. Doing it once in
the identity binder makes it true of every session-optional function,
which is what keeps the next terminal write from arriving with no author.
"""

from __future__ import annotations

from typing import Optional
from unittest import mock

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain import session_less_actor_binding as binding
from yoke_core.domain import yoke_function_actor_identity as identity
from yoke_core.domain.yoke_function_registry import RegistryEntry


class _Model(BaseModel):
    pass


def _entry(
    *,
    side_effects=("write",),
    ambient_session_required: bool = False,
    function_id: str = "project_structure.patch.apply",
) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda request: HandlerOutcome(result_payload={}, primary_success=True),
        request_model=_Model,
        response_model=_Model,
        stability="stable",
        owner_module="test",
        target_kinds=("project_structure",),
        side_effects=tuple(side_effects),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
        ambient_session_required=ambient_session_required,
    )


def _request(actor_id: Optional[str] = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="project_structure.patch.apply",
        actor=ActorContext(actor_id=actor_id, session_id=""),
        target=TargetRef(kind="global"),
    )


def _with_operating_actor(actor_id: Optional[str]):
    return mock.patch.object(binding, "operating_actor_id", return_value=actor_id)


def test_binds_the_operating_actor_when_the_envelope_carries_none():
    with _with_operating_actor("4"):
        bound = binding.bind_operating_actor(_request())
    assert bound.actor.actor_id == "4"


def test_an_actor_the_envelope_already_names_wins_untouched():
    # Over https that actor is the bearer token's, verified at the boundary.
    with _with_operating_actor("4"):
        bound = binding.bind_operating_actor(_request(actor_id="9"))
    assert bound.actor.actor_id == "9"


def test_an_unresolvable_actor_leaves_the_request_exactly_as_it_was():
    request = _request()
    with _with_operating_actor(None):
        assert binding.bind_operating_actor(request) is request


def test_the_binder_attributes_a_session_less_mutating_call():
    with mock.patch.object(
        binding,
        "bind_operating_actor",
        side_effect=lambda request: request.model_copy(
            update={"actor": request.actor.model_copy(update={"actor_id": "4"})}
        ),
    ):
        result = identity.bind_actor_identity(
            _entry(),
            _request(),
            ambient_session_id="",
        )
    assert result.error is None
    assert result.bound_request is not None
    assert result.bound_request.actor.actor_id == "4"


def test_the_binder_leaves_read_only_calls_alone():
    called = []
    with mock.patch.object(
        binding,
        "bind_operating_actor",
        side_effect=lambda request: called.append(request) or request,
    ):
        identity.bind_actor_identity(
            _entry(side_effects=()),
            _request(),
            ambient_session_id="",
        )
    assert called == []


def test_the_binder_attributes_a_read_answered_for_its_viewer():
    # A local plain terminal must learn the read's own answer (for example
    # that machine approval does not apply here), not actor_required.
    for function_id in ("machine_authorization.pending", "teammate_invites.list"):
        with _with_operating_actor("4"):
            result = identity.bind_actor_identity(
                _entry(side_effects=(), function_id=function_id),
                _request(),
                ambient_session_id="",
            )
        assert result.bound_request is not None
        assert result.bound_request.actor.actor_id == "4"


def test_a_session_requiring_function_still_refuses_rather_than_binding():
    called = []
    with mock.patch.object(
        binding,
        "bind_operating_actor",
        side_effect=lambda request: called.append(request) or request,
    ):
        result = identity.bind_actor_identity(
            _entry(ambient_session_required=True),
            _request(),
            ambient_session_id="",
        )
    assert result.error is not None
    assert result.error.error is not None
    assert result.error.error.code == "actor_session_missing"
    assert called == []


def test_operating_actor_id_is_none_without_a_local_control_plane():
    with mock.patch(
        "yoke_core.domain.control_plane_transport.local_connection_or_none",
        return_value=None,
    ):
        assert binding.operating_actor_id() is None
