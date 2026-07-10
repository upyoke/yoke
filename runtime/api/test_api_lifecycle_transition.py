"""Function-call coverage for ``lifecycle.transition.execute``.

Exercises the registered handler end-to-end via FastAPI's TestClient.
Covers AC-5.3 (typed source/target/reason payload routes through
backlog.execute_update), the source_status precondition path, the
gate-unmet error code mapping, frozen-item rejection, and the
claim_required_kind contract.

Function id rationale: the task spec named the function id
``lifecycle.transition`` (two segments), but task 1 closed a
``<family>.<subfamily>.<operation>`` three-segment registry contract.
We ship the canonical id ``lifecycle.transition.execute`` and lookup
the entry that way; AC-5.6's structural check is the lookup, not the
literal string.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.handlers.lifecycle_transition import (
    REGISTRATIONS as _LIFECYCLE_REGS,
)
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)


_SESSION_ID = "test-session-lifecycle"
_FUNCTION_ID = "lifecycle.transition.execute"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _lifecycle_envelope(item_id, target_status, **payload_overrides):
    payload = {"target_status": target_status}
    payload.update(payload_overrides)
    return {
        "function": _FUNCTION_ID,
        "version": "v1",
        "actor": {"actor_id": "op", "session_id": _SESSION_ID},
        "target": {"kind": "item", "item_id": item_id},
        "payload": payload,
    }


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def registered_lifecycle(test_db):
    """Reset and re-register the lifecycle.transition.execute handler.

    Same isolation pattern as the items.scalar.update test fixture: reset
    the process-level registry so sibling-test order doesn't matter, and
    suppress event emission + idempotency lookup so the dispatcher does
    not require a populated events table.
    """
    reset_registry_for_tests()
    for entry in _LIFECYCLE_REGS:
        register(**entry)
    p_event = patch.object(events_module, "emit_event")
    p_idem = patch.object(
        dispatch_module, "_idempotency_lookup", return_value=None,
    )
    p_event.start()
    p_idem.start()
    yield
    p_idem.stop()
    p_event.stop()
    reset_registry_for_tests()


def _claim_held() -> dict:
    return {"id": 1, "session_id": _SESSION_ID}


_UNSET = object()


def _post_lifecycle(test_db, envelope, claim_row=_UNSET):
    """Helper: invoke POST /v1/functions/call with claim-lookup patched.

    Sentinel default distinguishes "not provided" from explicit ``None``
    (the no-active-claim case).
    """
    target = _claim_held() if claim_row is _UNSET else claim_row
    with patch.object(
        claims_module, "who_claims_for_item", return_value=target,
    ):
        with _client_for_db(test_db["db_path"]) as client:
            return client.post("/v1/functions/call", json=envelope)


def _seed_qa_requirement(db_path, item_id, qa_phase="verification"):
    conn = connect_test_db(db_path)
    p = _p(conn)
    # Omit the autoincrement id so the identity/rowid default fires on both
    # backends (an explicit NULL violates the Postgres identity column).
    conn.execute(
        f"""INSERT INTO qa_requirements
           (item_id, qa_kind, qa_phase, blocking_mode,
            requirement_source, success_policy, created_at)
           VALUES ({p}, 'ac_verification', {p}, 'blocking',
                   'explicit', 'blocking', '2026-04-01T00:00:00Z')""",
        (item_id, qa_phase),
    )
    conn.commit()
    conn.close()


def _seed_work_claim(db_path, item_id=1, session_id=_SESSION_ID):
    conn = connect_test_db(db_path)
    p = _p(conn)
    conn.execute(
        f"""INSERT INTO work_claims
           (session_id, target_kind, item_id, claim_type, claimed_at,
            last_heartbeat)
           VALUES ({p}, 'item', {p}, 'exclusive',
                   '2026-04-01T00:00:00Z', '2026-04-01T00:00:00Z')""",
        (session_id, item_id),
    )
    conn.commit()
    conn.close()


def _clear_process_session_env(monkeypatch):
    for name in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(name, raising=False)


class TestLifecycleTransitionRoutesThroughExecuteUpdate:
    """AC-5.3: typed payload routes through the same engines as
    ``service_client advance/...`` (i.e. ``backlog.execute_update``)."""

    def test_typed_payload_writes_status(
        self, registered_lifecycle, test_db, monkeypatch,
    ):
        _seed_qa_requirement(test_db["db_path"], 1)
        _seed_work_claim(test_db["db_path"], 1)
        _clear_process_session_env(monkeypatch)
        resp = _post_lifecycle(
            test_db,
            _lifecycle_envelope(
                1, "reviewing-implementation",
                source_status="implementing",
                reason="implementation complete; ready for review",
                qa_bypass=True,
            ),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"], body
        result = body["result"]
        assert result["from_status"] == "implementing"
        assert result["to_status"] == "reviewing-implementation"
        assert result["reason"] == "implementation complete; ready for review"
        # Verify the DB write landed.
        conn = connect_test_db(test_db["db_path"])
        row = conn.execute("SELECT status FROM items WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "reviewing-implementation"


class TestLifecycleTransitionPreconditions:
    def test_source_status_mismatch_returns_precondition_failed(
        self, registered_lifecycle, test_db,
    ):
        """source_status mismatch is a structural precondition, not a gate."""
        resp = _post_lifecycle(
            test_db,
            _lifecycle_envelope(
                1, "reviewing-implementation",
                source_status="reviewing-implementation",
            ),
        )
        # Item 1 is 'implementing', not 'reviewing-implementation' -> mismatch.
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "precondition_failed"

    def test_missing_item_without_project_fails_closed(
        self, registered_lifecycle, test_db,
    ):
        resp = _post_lifecycle(
            test_db,
            _lifecycle_envelope(99999, "reviewing-implementation"),
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["error"]["code"] == "permission_denied"


class TestLifecycleTransitionGateMapping:
    """AC-5.2 parity: QA gate failures map to lifecycle_gate_unmet."""

    def test_gate_unmet_returns_lifecycle_gate_unmet(
        self, registered_lifecycle, test_db, monkeypatch,
    ):
        # Item 1 in 'implementing' with no qa_requirements -> GATE_QA_REVIEWING.
        monkeypatch.setenv("YOKE_CLAIM_BYPASS", "test-isolation")
        resp = _post_lifecycle(
            test_db,
            _lifecycle_envelope(1, "reviewing-implementation"),
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "lifecycle_gate_unmet"


class TestLifecycleTransitionFrozenRejection:
    """AC-5.4 parity: frozen items refuse status transitions."""

    def test_frozen_item_rejection(self, registered_lifecycle, test_db):
        conn = connect_test_db(test_db["db_path"])
        conn.execute("UPDATE items SET frozen = 1 WHERE id = 1")
        conn.commit()
        conn.close()
        resp = _post_lifecycle(
            test_db,
            _lifecycle_envelope(1, "reviewing-implementation"),
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "frozen"


class TestLifecycleTransitionClaimRequired:
    """AC-5.6: registered claim_required_kind='item' + claim-path coverage."""

    def test_claim_required_kind_is_item(self, registered_lifecycle):
        from yoke_core.domain.yoke_function_registry import lookup
        entry = lookup(_FUNCTION_ID)
        assert entry is not None
        assert entry.claim_required_kind == "item"

    def test_call_without_claim_returns_claim_required(
        self, registered_lifecycle, test_db,
    ):
        resp = _post_lifecycle(
            test_db,
            _lifecycle_envelope(1, "reviewing-implementation"),
            claim_row=None,
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "claim_required"

    def test_call_with_mismatched_session_returns_claim_required(
        self, registered_lifecycle, test_db,
    ):
        resp = _post_lifecycle(
            test_db,
            _lifecycle_envelope(1, "reviewing-implementation"),
            claim_row={"id": 1, "session_id": "OTHER-SESSION"},
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "claim_required"
