"""Session HTTP routes encode native facts without changing domain results."""

import json
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.api.routes import sessions_claims as claims
from yoke_core.api.routes import sessions_inventory as inventory
from yoke_core.api.routes import sessions_lifecycle as lifecycle

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
OPAQUE = "captured 2026-10-09 10:26:12+00:00"


@pytest.mark.parametrize(
    "module,owner,invoke,collection,outer",
    [
        (
            lifecycle,
            "register_session",
            lambda: lifecycle.api_register_session(
                lifecycle.RegisterSessionRequest(
                    session_id="clock-wire",
                    executor="claude-code",
                    provider="anthropic",
                    workspace="/tmp/clock-wire",
                    project_id=1,
                )
            ),
            False,
            None,
        ),
        (
            lifecycle,
            "heartbeat",
            lambda: lifecycle.api_heartbeat("clock-wire"),
            False,
            None,
        ),
        (
            lifecycle,
            "end_session",
            lambda: lifecycle.api_end_session("clock-wire"),
            False,
            None,
        ),
        (
            lifecycle,
            "clean_stale_harness_sessions",
            lambda: lifecycle.api_reclaim_stale(10, 90),
            False,
            None,
        ),
        (
            claims,
            "claim_work",
            lambda: claims.api_claim_work(
                "clock-wire", claims.ClaimWorkRequest(item_id="7")
            ),
            False,
            None,
        ),
        (
            claims,
            "release_claim",
            lambda: claims.api_release_claim(7, claims.ReleaseClaimRequest()),
            False,
            None,
        ),
        (
            claims,
            "handoff_claim",
            lambda: claims.api_handoff_claim(
                7, claims.HandoffClaimRequest(target_session_id="clock-next")
            ),
            False,
            None,
        ),
        (
            inventory,
            "list_harness_sessions",
            lambda: inventory.api_list_sessions(None, None, None),
            True,
            "sessions",
        ),
        (
            inventory,
            "list_claims_for_session",
            lambda: inventory.api_list_session_claims("clock-wire"),
            True,
            "claims",
        ),
        (
            inventory,
            "get_claim_for_work_unit",
            lambda: inventory.api_get_claim_by_work_unit("7"),
            False,
            "claim",
        ),
        (
            inventory,
            "find_stale_sessions",
            lambda: inventory.api_list_stale_sessions(10),
            True,
            "sessions",
        ),
    ],
)
def test_native_session_result_formats_at_http_boundary_only(
    monkeypatch, module, owner, invoke, collection, outer
):
    closed = []
    conn = SimpleNamespace(close=lambda: closed.append(True))
    api = SimpleNamespace(get_db_readwrite=lambda: conn, get_db_readonly=lambda: conn)
    monkeypatch.setattr(module, "_main_api", lambda: api)
    monkeypatch.setattr(lifecycle, "resolve_execution_level", lambda **kwargs: "SENIOR")
    monkeypatch.setattr(lifecycle, "session_levels", lambda *_args: [])
    fact = {
        "last_heartbeat": MOMENT,
        "ended_at": None,
        "offer_envelope": {"observed_at": OPAQUE},
        "id": "2026-10-09",
    }
    result = [fact] if collection else fact
    calls = []

    def domain(received, *args, **kwargs):
        assert received is conn
        calls.append(True)
        return result

    monkeypatch.setattr(module, owner, domain)
    response = invoke()
    assert response.status_code in (200, 201)
    body = json.loads(response.body)
    if outer is not None:
        body = body[outer]
    if collection:
        body = body[0]
    assert body == {**fact, "last_heartbeat": "2026-10-09T10:26:12.345678Z"}
    assert fact["last_heartbeat"] is MOMENT
    assert fact["offer_envelope"]["observed_at"] == OPAQUE
    assert calls == closed == [True]


def test_missing_claim_remains_null_at_http_boundary(monkeypatch):
    conn = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(
        inventory, "_main_api", lambda: SimpleNamespace(get_db_readonly=lambda: conn)
    )
    monkeypatch.setattr(
        inventory, "get_claim_for_work_unit", lambda *_args, **kwargs: None
    )
    assert json.loads(inventory.api_get_claim_by_work_unit("7").body) == {"claim": None}
