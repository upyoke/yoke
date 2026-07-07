"""Path-claim ownership regressions for HC-claim-boundary-audit."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from yoke_core.domain import check_claim_boundary_audit_cutoff as _cutoff
from runtime.api.engines.test_doctor_hc_claim_boundary_audit import (
    _add_claim,
    _add_event,
    _add_session,
    _p,
    _run,
    _sid,
    env,
)


@pytest.fixture(autouse=True)
def _disable_event_id_cutoff(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_cutoff, "read_min_event_id_cutoff", lambda: 0)
    yield


def _add_path_claim(
    conn: Any,
    *,
    claim_id: int,
    sid: str,
    item_id: int,
    owner_item_id: int | None,
) -> None:
    p = _p(conn)
    actor_component = f"test-claim-boundary-{uuid.uuid4()}"
    cur = conn.execute(
        "INSERT INTO actors (kind, system_component, created_at)"
        f" VALUES ('system', {p}, '2026-05-17T11:00:00Z')"
        " RETURNING id",
        (actor_component,),
    )
    actor_id = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claims (id, state, mode, actor_id, session_id,"
        " item_id, owner_kind, owner_item_id, integration_target,"
        " registered_at)"
        f" VALUES ({p}, 'active', 'exclusive', {p}, {p}, {p}, 'item',"
        f" {p}, 'main', '2026-05-17T11:00:00Z')",
        (claim_id, actor_id, sid, item_id, owner_item_id),
    )
    conn.commit()


def test_path_claim_amendment_pass_for_item_owned_provenance_event(env):
    conn = env["conn"]
    holder, registrar = _sid("x"), _sid("y")
    _add_session(conn, holder)
    _add_session(conn, registrar)
    _add_claim(conn, holder, 913, claimed_at="2026-05-17T11:00:00Z")
    _add_path_claim(
        conn,
        claim_id=52,
        sid=registrar,
        item_id=913,
        owner_item_id=913,
    )
    _add_event(
        conn, "PathClaimAmended", registrar, 913,
        {"claim_id": 52, "amendment_kind": "widen"},
    )
    rec = _run(conn)
    assert rec.results[0].result == "PASS"


def test_path_claim_amendment_fail_when_item_owner_mismatches(env):
    conn = env["conn"]
    holder, registrar = _sid("j"), _sid("k")
    _add_session(conn, holder)
    _add_session(conn, registrar)
    _add_claim(conn, holder, 914, claimed_at="2026-05-17T11:00:00Z")
    _add_path_claim(
        conn,
        claim_id=53,
        sid=registrar,
        item_id=914,
        owner_item_id=999,
    )
    _add_event(
        conn, "PathClaimAmended", registrar, 914,
        {"claim_id": 53, "amendment_kind": "widen"},
    )
    rec = _run(conn)
    result = rec.results[0]
    assert result.result == "FAIL"
    assert "path_claim_mutation_without_owning_claim" in result.detail
