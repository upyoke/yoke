"""Contract coverage across the real claim-holder dispatcher envelope."""

from __future__ import annotations

from unittest.mock import MagicMock

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import (
    db_backend,
    db_helpers,
    yoke_function_dispatch as dispatch_module,
    yoke_function_dispatch_events as events_module,
)
from yoke_core.domain.handlers import claims_work_holders
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.work_claim_targets import item_id_from_row
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def test_holder_list_envelope_keeps_scope_exact_and_decodable(
    monkeypatch,
) -> None:
    row = {
        "id": 77,
        "session_id": "sess-1",
        "target_kind": "item",
        "scope": {"item_id": 42},
        "claimed_at": "2026-08-29T15:00:00Z",
        "last_heartbeat": "2026-08-29T15:01:00Z",
    }
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = None
    conn.execute.return_value.fetchall.return_value = [row]

    reset_registry_for_tests()
    register_all_handlers()
    monkeypatch.setenv("YOKE_SESSION_ID", "sess-1")
    monkeypatch.setattr(dispatch_module, "_idempotency_lookup", lambda *_a, **_k: None)
    monkeypatch.setattr(events_module, "emit_event", MagicMock())
    monkeypatch.setattr(db_helpers, "connect", lambda: conn)
    monkeypatch.setattr(db_backend, "connection_is_postgres", lambda _conn: False)
    monkeypatch.setattr(
        claims_work_holders,
        "_lane_worktrees",
        lambda _conn, _holders: {77: ["/repo/.worktrees/lane"]},
    )
    monkeypatch.setattr(
        claims_work_holders,
        "_current_item_before_implementation",
        lambda _conn, _session_id: False,
    )
    lookup = MagicMock(side_effect=AssertionError("contract id was enriched"))
    monkeypatch.setattr(
        "yoke_core.domain.item_ref_render.render_item_ref_lookup",
        lookup,
    )

    try:
        response = dispatch(
            FunctionCallRequest(
                function="claims.work.holder_list",
                actor=ActorContext(actor_id="2", session_id="sess-1"),
                target=TargetRef(kind="global"),
                payload={"session_id": "sess-1"},
            )
        )
    finally:
        reset_registry_for_tests()

    assert response.success, response.error
    holder = response.result["holders"][0]
    assert holder["scope"] == {"item_id": 42}
    assert item_id_from_row(holder) == 42
    lookup.assert_not_called()
