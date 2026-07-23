"""Ambient-session gate boundary for project-owned deployment-flow writes.

`deployment_flows.reconcile_project` is materialized by
`yoke project install` / `refresh` / `onboard` in a plain terminal with no
harness session, so it must bind session-less. The operator-only
flow-definition writes (`set_status` / `update_stages`) are not on the
bootstrap path and stay session-gated. This is the regression guard for the
bootstrap/config session-optional class boundary.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.yoke_function_actor_identity import bind_actor_identity
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_deployment_reconcile_skips_session_gate_but_operator_flows_do_not() -> None:
    init_register.register_all_handlers()

    reconcile = yoke_function_registry.lookup(
        "deployment_flows.reconcile_project"
    )
    assert reconcile is not None
    assert reconcile.ambient_session_required is False
    bound = bind_actor_identity(
        reconcile,
        FunctionCallRequest(
            function="deployment_flows.reconcile_project",
            actor=ActorContext(session_id=""),
            target=TargetRef(kind="global", project_id="acme"),
            payload={"schema": 1, "flows": []},
        ),
        ambient_session_id="",
    )
    assert bound.error is None
    assert bound.bound_request is not None
    assert bound.bound_request.actor.session_id == ""

    for function_id in (
        "deployment_flows.set_status",
        "deployment_flows.update_stages",
    ):
        entry = yoke_function_registry.lookup(function_id)
        assert entry is not None
        assert entry.ambient_session_required is True
        denied = bind_actor_identity(
            entry,
            FunctionCallRequest(
                function=function_id,
                actor=ActorContext(session_id=""),
                target=TargetRef(kind="global"),
                payload={},
            ),
            ambient_session_id="",
        )
        assert denied.error is not None
        assert denied.error.error is not None
        assert denied.error.error.code == "actor_session_missing"
