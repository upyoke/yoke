"""Governed stale-session browser action contracts."""

from unittest.mock import call, patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.sessions_reclaim import (
    handle_sessions_reclaim_stale,
)


def _request(confirm=False, project_ids=None):
    payload = {"confirm": confirm}
    if project_ids is not None:
        payload["project_ids"] = project_ids
    return FunctionCallRequest(
        function="sessions.reclaim_stale",
        actor=ActorContext(actor_id="2", session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_reclaim_requires_explicit_confirmation():
    outcome = handle_sessions_reclaim_stale(_request())
    assert not outcome.primary_success
    assert outcome.error.code == "confirmation_required"


def test_reclaim_returns_sweep_receipt_for_global_and_project_scopes():
    class _Connection:
        def close(self):
            pass

    receipt = {
        "never_engaged": [],
        "heartbeat_stale": [{"session_id": "stale"}],
        "progress_stale": [],
        "skipped_between_turns": [],
        "total_reclaimed": 1,
        "scratch_cleanup": {},
    }
    connection = _Connection()
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=connection,
        ),
        patch(
            "yoke_core.domain.sessions_cleanup.clean_stale_harness_sessions",
            return_value=receipt,
        ) as sweep,
    ):
        global_outcome = handle_sessions_reclaim_stale(_request(confirm=True))
        scoped_outcome = handle_sessions_reclaim_stale(
            _request(confirm=True, project_ids=[1, 2]),
        )

    assert global_outcome.primary_success
    assert global_outcome.result_payload == receipt
    assert scoped_outcome.primary_success
    assert scoped_outcome.result_payload == receipt
    assert sweep.call_args_list == [
        call(connection, project_ids=None),
        call(connection, project_ids=[1, 2]),
    ]


def test_reclaim_is_registered_as_an_org_admin_mutation():
    from yoke_core.domain import yoke_function_registry as registry
    from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN
    from yoke_core.domain.function_authz_product_scopes import (
        PRODUCT_AUTHZ_BY_ID,
    )
    from yoke_core.domain.handlers.__init_register__ import (
        register_all_handlers,
    )

    registry.reset_registry_for_tests()
    try:
        register_all_handlers()
        entry = registry.lookup("sessions.reclaim_stale")
        assert entry is not None
        assert entry.side_effects
        assert "liveness_recheck" in entry.guardrails
        assert "project_scope_exact" in entry.guardrails
        assert PRODUCT_AUTHZ_BY_ID["sessions.reclaim_stale"].permission_key == (
            PERM_ORG_ADMIN
        )
    finally:
        registry.reset_registry_for_tests()
