"""Actor-identity regression tests for the advance implementation-entry
orchestrator. Sibling of ``test_advance_implementation_entry.py``.
"""

from __future__ import annotations

from typing import Any, List

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
)
from yoke_core.engines import advance_implementation_entry as orch


def _ok_response() -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function="lifecycle.transition.execute", version="v1",
        result={"from_status": "refined-idea", "to_status": "implementing"},
    )


def test_flip_status_leaves_actor_id_empty(monkeypatch):
    """``_flip_status`` constructs an ``ActorContext`` whose ``actor_id`` is
    empty so the actor-identity resolver auto-binds the session-resolved
    value. A non-empty literal here is rejected by the mutating-call gate."""
    captured: List[Any] = []

    def fake_dispatch(req):
        captured.append(req)
        return _ok_response()

    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch.dispatch", fake_dispatch,
    )
    orch._flip_status(
        42, from_status="refined-idea", to_status="implementing",
        session_id="sess-xyz", force=False, qa_bypass=False,
    )
    assert len(captured) == 1
    req = captured[0]
    assert req.actor.session_id == "sess-xyz"
    assert (req.actor.actor_id or "") == ""


def test_flip_status_accepted_by_actor_identity_gate(monkeypatch):
    """The orchestrator's finalize envelope passes the actor-identity binder
    without raising ``actor_id_mismatch``. The resolver auto-binds the
    session-derived actor_id; the binder returns ``BoundIdentity`` with no
    error."""
    from yoke_core.domain.yoke_function_actor_identity import (
        ActorLookup,
        _bind_actor_id,
    )
    from yoke_core.domain.yoke_function_registry import lookup

    captured: List[Any] = []

    def fake_dispatch(req):
        captured.append(req)
        return _ok_response()

    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch.dispatch", fake_dispatch,
    )
    orch._flip_status(
        42, from_status="refined-idea", to_status="implementing",
        session_id="sess-xyz", force=False, qa_bypass=False,
    )

    # ``orch._flip_status`` only triggers handler registration via the real
    # dispatch path; we monkeypatched dispatch above, so register handlers
    # explicitly here before looking up the lifecycle entry.
    from yoke_core.domain.handlers.__init_register__ import (
        register_all_handlers,
    )
    register_all_handlers()

    req = captured[0]
    entry = lookup(req.function)
    assert entry is not None, f"registry lookup failed for {req.function!r}"
    bound = _bind_actor_id(
        entry, req,
        payload_session_id="sess-xyz", ambient_session_id="sess-xyz",
        actor_id_resolver=lambda _sid: ActorLookup(
            actor_id="2", session_found=True,
        ),
        read_only=False,
        explicit_override=False,
    )
    assert bound.error is None, (
        f"actor-identity binder rejected the orchestrator's finalize "
        f"envelope: {bound.error}"
    )
    assert bound.bound_request.actor.actor_id == "2"
