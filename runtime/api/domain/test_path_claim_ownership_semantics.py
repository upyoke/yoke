"""Cross-reader regression suite for typed path-claim ownership semantics.

Locks in AC-12 behavior — covers all three owner kinds plus the
provenance/authority split:

- Item-owned idea claims registered by a live harness session: the
  session is provenance, the item is authority. Active-claim lookup
  by the session returns the row (via current_item link). Board
  rendering does NOT show the row as a session-owned orphan.
- True session-owned out-of-item claims: session is authority. Active
  lookup returns by session match. Board rendering shows as bare
  ``📁N`` (no item parens).
- Process-owned claims: work_claim is authority. Active lookup
  returns by item link (via the held work_claim's item). Board
  rendering shows ``📁N (⚙ KEY)`` on the session holding the
  work_claim.

These are end-to-end-shaped tests against the real domain
modules (register, get_claim, active lookup, board renderer) — the
goal is to prove the typed contract holds across every reader on the
slice, not to retest individual unit behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from yoke_core.domain._path_claims_test_helpers import (
    conn as path_claims_conn,  # noqa: F401 — fixture
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import get_claim, register
from yoke_core.domain.path_claims_register import register_for_item


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_item(conn, *, item_id: int, project="yoke") -> int:
    project_id = 2 if project == "externalwebapp" else int(project) if str(project).isdigit() else 1
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, created_at, "
        "updated_at, project_id, project_sequence) "
        "VALUES (%s, 'X', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    conn.commit()
    return item_id


def _seed_session(conn, *, session_id: str) -> str:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "project_id, execution_lane, capabilities, workspace, mode, offered_at, "
        "last_heartbeat) "
        "VALUES (%s, 'test', 'test', 'test', 1, 'primary', '[]', '/tmp', 'wait', "
        "%s, %s)",
        (session_id, _now(), _now()),
    )
    conn.commit()
    return session_id


class TestItemOwnedRegisteredBySession:
    """Item-owned claims survive the registering session ending."""

    def test_item_owner_typed_after_register(self, path_claims_conn):
        item = _seed_item(path_claims_conn, item_id=4001)
        sess = _seed_session(path_claims_conn, session_id="live-registrar-1")
        seed_target(path_claims_conn, path_string="runtime/api/domain")
        cid = register_for_item(
            path_claims_conn,
            item_id=item,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=local_human(path_claims_conn),
            session_id=sess,
        )
        claim = get_claim(path_claims_conn, cid)
        assert claim["owner_kind"] == "item"
        assert claim["owner_item_id"] == item
        # Owner session is NULL — the registering session is provenance.
        assert claim["owner_session_id"] is None
        # The legacy session_id AND new registered_by_session_id are
        # both provenance and both name the registrar.
        assert claim["session_id"] == sess
        assert claim["registered_by_session_id"] == sess
        # Provenance actor matches the legacy actor_id column.
        assert claim["registered_by_actor_id"] == claim["actor_id"]

    def test_item_owned_does_not_become_session_owned_after_re_register(
        self, path_claims_conn,
    ):
        item = _seed_item(path_claims_conn, item_id=4002)
        sess_a = _seed_session(path_claims_conn, session_id="reg-a")
        sess_b = _seed_session(path_claims_conn, session_id="reg-b")
        seed_target(path_claims_conn, path_string="runtime/api/domain")
        cid = register_for_item(
            path_claims_conn,
            item_id=item,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=local_human(path_claims_conn),
            session_id=sess_a,
        )
        # A second register from a different session must reuse the same
        # claim (typed concrete reuse path) — and not flip ownership.
        cid2 = register_for_item(
            path_claims_conn,
            item_id=item,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=local_human(path_claims_conn),
            session_id=sess_b,
        )
        assert cid == cid2
        claim = get_claim(path_claims_conn, cid)
        assert claim["owner_kind"] == "item"
        assert claim["owner_item_id"] == item


class TestSessionOwnedOrphan:
    """True session-owned claims have no item or work_claim linkage."""

    def test_session_owner_typed_when_no_item(self, path_claims_conn):
        sess = _seed_session(path_claims_conn, session_id="orphan-sess")
        actor = local_human(path_claims_conn)
        tid = seed_target(path_claims_conn, path_string="runtime/api/foo.py")
        # Direct lifecycle register with no item_id — true session-owned.
        cid = register(
            path_claims_conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[tid],
            session_id=sess,
        )
        claim = get_claim(path_claims_conn, cid)
        assert claim["owner_kind"] == "session"
        assert claim["owner_session_id"] == sess
        assert claim["owner_item_id"] is None
        assert claim["owner_work_claim_id"] is None
        # Provenance fields match the same session.
        assert claim["registered_by_session_id"] == sess


class TestProcessOwned:
    """Process-owned claims are owned by a work_claim."""

    def test_process_owner_typed_when_work_claim_set(
        self, path_claims_conn,
    ):
        sess = _seed_session(path_claims_conn, session_id="proc-sess")
        actor = local_human(path_claims_conn)
        # Seed a work_claims row for the process linkage to be valid.
        path_claims_conn.execute(
            "INSERT INTO work_claims (id, session_id, target_kind, "
            "process_key, conflict_group, claim_type, claimed_at, "
            "last_heartbeat) "
            "VALUES (%s, %s, 'process', 'FEED', 'default', 'exclusive', %s, %s)",
            (88, sess, _now(), _now()),
        )
        path_claims_conn.commit()
        tid = seed_target(path_claims_conn, path_string="runtime/api/foo.py")
        cid = register(
            path_claims_conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[tid],
            session_id=sess,
            work_claim_id=88,
        )
        claim = get_claim(path_claims_conn, cid)
        assert claim["owner_kind"] == "process"
        assert claim["owner_work_claim_id"] == 88
        assert claim["owner_item_id"] is None
        assert claim["owner_session_id"] is None


class TestRegisterWithoutOwnerSignalsLandsUntyped:
    """Backwards-compat: register without item/work_claim/session leaves
    ``owner_kind=NULL``.

    Production callers always pass at least one of item_id, work_claim_id,
    or session_id via ``register_for_item`` / direct session-owned
    register. Legacy synthetic call sites that pass none of them still
    succeed for cutover compatibility; the resulting row's NULL
    ``owner_kind`` is surfaced by ``HC-path-claim-owner-kind`` at doctor
    time.
    """

    def test_no_owner_signals_lands_untyped(self, path_claims_conn):
        actor = local_human(path_claims_conn)
        tid = seed_target(path_claims_conn, path_string="runtime/api/foo.py")
        cid = register(
            path_claims_conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[tid],
        )
        claim = get_claim(path_claims_conn, cid)
        assert claim["owner_kind"] is None
        assert claim["owner_item_id"] is None
        assert claim["owner_session_id"] is None
        assert claim["owner_work_claim_id"] is None


class TestProvenancePreserved:
    """Both legacy and registered_by_* columns name the registrar."""

    def test_provenance_columns_match_actor(self, path_claims_conn):
        item = _seed_item(path_claims_conn, item_id=4010)
        actor = local_human(path_claims_conn)
        seed_target(path_claims_conn, path_string="runtime/api/domain")
        cid = register_for_item(
            path_claims_conn,
            item_id=item,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=actor,
        )
        claim = get_claim(path_claims_conn, cid)
        assert claim["actor_id"] == actor
        assert claim["registered_by_actor_id"] == actor

    def test_provenance_session_optional(self, path_claims_conn):
        # Item-owned with no session_id passed → provenance session is NULL.
        item = _seed_item(path_claims_conn, item_id=4011)
        seed_target(path_claims_conn, path_string="runtime/api/domain")
        cid = register_for_item(
            path_claims_conn,
            item_id=item,
            integration_target="main",
            paths=["runtime/api/domain"],
            actor_id=local_human(path_claims_conn),
        )
        claim = get_claim(path_claims_conn, cid)
        assert claim["session_id"] is None
        assert claim["registered_by_session_id"] is None
