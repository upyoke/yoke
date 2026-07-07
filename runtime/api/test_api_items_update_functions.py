"""Function-call coverage for ``items.scalar.update``.

Exercises the registered handler end-to-end via FastAPI's TestClient.
Covers AC-5.1 (status routes through prepare_update), AC-5.2 (gate-unmet
error code mapping), AC-5.4 (frozen-item rejection), AC-5.6 (registered
claim_required_kind), and the claim-required path. The sibling file
``test_api_items_update.py`` covers the PATCH /v1/items/{id} HTTP route
against the same mutation gate chain.
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
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.handlers.items_scalar import REGISTRATIONS as _SCALAR_REGS
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)


_SESSION_ID = "test-session-scalar"


def _scalar_envelope(item_id, **payload_overrides):
    payload = {
        "field": payload_overrides.pop("field", "title"),
        "value": payload_overrides.pop("value", "Updated via function call"),
    }
    payload.update(payload_overrides)
    return {
        "function": "items.scalar.update",
        "version": "v1",
        "actor": {"actor_id": "op", "session_id": _SESSION_ID},
        "target": {"kind": "item", "item_id": item_id},
        "payload": payload,
    }


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def registered_scalar(test_db):
    """Reset and re-register the items.scalar.update handler.

    The FastAPI lifespan calls register_all_handlers() at app startup, so
    each TestClient context re-registers everything. We reset+re-register
    here to isolate from sibling-test pollution and short-circuit
    lifespan-triggered duplicate registrations (the registry raises
    RegistryDuplicateError on a second register call).
    """
    reset_registry_for_tests()
    for entry in _SCALAR_REGS:
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


def _post_scalar(test_db, envelope, claim_row=_UNSET):
    """Helper: invoke POST /v1/functions/call with claim-lookup patched.

    Pass ``claim_row=None`` to simulate "no active claim" — the default
    sentinel distinguishes "not provided" (use held claim) from "explicit
    None" (no claim row).
    """
    target = _claim_held() if claim_row is _UNSET else claim_row
    with patch.object(
        claims_module, "who_claims_for_item", return_value=target,
    ):
        with _client_for_db(test_db["db_path"]) as client:
            return client.post("/v1/functions/call", json=envelope)


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


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


class TestScalarUpdateRoutesThroughPrepareUpdate:
    """AC-5.1: function-call surface shares the PATCH route's gate path."""

    def test_status_field_writes_db_row(
        self, registered_scalar, test_db, monkeypatch,
    ):
        # Seed qa_requirement so the reviewing-implementation gate is happy.
        conn = connect_test_db(test_db["db_path"])
        # Omit the autoincrement id so the identity/rowid default fires on both
        # backends (an explicit NULL violates the Postgres identity column).
        conn.execute(
            """INSERT INTO qa_requirements
               (item_id, qa_kind, qa_phase, blocking_mode,
                requirement_source, success_policy, created_at)
               VALUES (1, 'ac_verification', 'verification', 'blocking',
                       'explicit', 'blocking', '2026-04-01T00:00:00Z')"""
        )
        conn.commit()
        conn.close()
        _seed_work_claim(test_db["db_path"], 1)
        _clear_process_session_env(monkeypatch)
        resp = _post_scalar(
            test_db,
            _scalar_envelope(
                1, field="status", value="reviewing-implementation",
                qa_bypass=True,
            ),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"], body
        assert body["result"]["field"] == "status"
        assert body["result"]["value"] == "reviewing-implementation"
        conn = connect_test_db(test_db["db_path"])
        row = conn.execute("SELECT status FROM items WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "reviewing-implementation"

    def test_title_field_round_trips(self, registered_scalar, test_db):
        resp = _post_scalar(
            test_db,
            _scalar_envelope(1, field="title", value="Title via FC"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["value"] == "Title via FC"

    def test_priority_field_round_trips(self, registered_scalar, test_db):
        resp = _post_scalar(
            test_db,
            _scalar_envelope(1, field="priority", value="low"),
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["value"] == "low"


class TestScalarUpdateGateMapping:
    """AC-5.2: gate-unmet codes collapse to lifecycle_gate_unmet (HTTP 422)."""

    def test_status_gate_unmet_returns_lifecycle_gate_unmet(
        self, registered_scalar, test_db, monkeypatch,
    ):
        # Item 1 is in 'implementing' with no qa_requirements seeded, so a
        # reviewing-implementation transition triggers GATE_QA_REVIEWING in
        # the mutation layer. The gate fires before claim verification, so
        # the bypass is only needed for parity with the happy-path test.
        monkeypatch.setenv("YOKE_CLAIM_BYPASS", "test-isolation")
        resp = _post_scalar(
            test_db,
            _scalar_envelope(
                1, field="status", value="reviewing-implementation",
            ),
        )
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert not body["success"]
        assert body["error"]["code"] == "lifecycle_gate_unmet"

    def test_invalid_priority_returns_validation_error(
        self, registered_scalar, test_db,
    ):
        resp = _post_scalar(
            test_db,
            _scalar_envelope(1, field="priority", value="critical"),
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "validation_error"


class TestScalarUpdateFrozenRejection:
    """AC-5.4: frozen-item update returns error.code='frozen' (HTTP 422)."""

    def test_frozen_item_rejection(self, registered_scalar, test_db):
        conn = connect_test_db(test_db["db_path"])
        conn.execute("UPDATE items SET frozen = 1 WHERE id = 1")
        conn.commit()
        conn.close()
        resp = _post_scalar(
            test_db,
            _scalar_envelope(1, field="title", value="Will not stick"),
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "frozen"

    def test_frozen_field_toggle_is_allowed_even_when_frozen(
        self, registered_scalar, test_db,
    ):
        """The frozen field itself is exempt so operators can thaw items."""
        conn = connect_test_db(test_db["db_path"])
        conn.execute("UPDATE items SET frozen = 1 WHERE id = 1")
        conn.commit()
        conn.close()
        resp = _post_scalar(
            test_db, _scalar_envelope(1, field="frozen", value=False),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"]


class TestScalarUpdateClaimRequired:
    """AC-5.6 + claim-required path coverage."""

    def test_claim_required_kind_is_item(self, registered_scalar):
        from yoke_core.domain.yoke_function_registry import lookup
        entry = lookup("items.scalar.update")
        assert entry is not None
        assert entry.claim_required_kind == "item"

    def test_call_without_claim_returns_claim_required(
        self, registered_scalar, test_db,
    ):
        """Session without an active claim sees error.code='claim_required'."""
        resp = _post_scalar(
            test_db,
            _scalar_envelope(1, field="title", value="No claim"),
            claim_row=None,
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "claim_required"

    def test_call_with_mismatched_session_returns_claim_required(
        self, registered_scalar, test_db,
    ):
        """Session id mismatch is rejected with claim_required."""
        resp = _post_scalar(
            test_db,
            _scalar_envelope(1, field="title", value="Mismatch"),
            claim_row={"id": 1, "session_id": "OTHER-SESSION"},
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "claim_required"
