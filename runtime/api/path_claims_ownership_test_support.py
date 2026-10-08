# ruff: noqa: F811
"""Seeded holder/intruder state for path-claim ownership tests.

One item, a holder session owning its work claim, an intruder session that
does not, and a planned path claim over two targets — with every dispatcher
surface pointed at the in-memory test connection.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import (
    path_claims_dispatch,
    path_claims_dispatch_amend,
    path_claims_dispatch_narrow,
    path_claims_dispatch_state,
)
from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.work_claim_targets import make_item_target


HOLDER_SESSION = "sess-holder-ownership"
INTRUDER_SESSION = "sess-intruder-ownership"
ITEM_ID = 9001


def seed_item(conn, *, item_id=ITEM_ID, project="yoke"):
    project_key = str(project)
    project_id = (
        2
        if project_key == "externalwebapp"
        else int(project_key)
        if project_key.isdigit()
        else 1
    )
    conn.execute(
        "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 't', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )


def seed_session(conn, session_id):
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, "
        "model, project_id, execution_level, executor_version, machine_id, workspace, mode, "
        "offered_at, last_heartbeat) "
        "VALUES (%s, 'claude-code', 'test', 'test', 1, 'primary', NULL, NULL, '/tmp', "
        "'active', '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
        (session_id,),
    )


def seed_work_claim(conn, *, session_id, item_id=ITEM_ID):
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, "
        "claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, '2026-05-01T00:00:00Z', "
        "'2026-05-01T00:00:00Z')",
        (session_id, make_item_target(item_id).scope_json()),
    )


def seed_path_claim(conn, *, actor_id, item_id=ITEM_ID, target_ids=()):
    cur = conn.execute(
        "INSERT INTO path_claims (state, mode, owner_kind, owner_item_id, "
        "registered_by_actor_id, integration_target, registered_at) "
        "VALUES ('planned', 'exclusive', 'item', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z') RETURNING id",
        (item_id, actor_id),
    )
    claim_id = int(cur.fetchone()[0])
    for tid in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) VALUES (%s, %s, '2026-05-01T00:00:00Z')",
            (claim_id, tid),
        )
    return claim_id


def projection_snapshot(conn, claim_id):
    pc = conn.execute(
        "SELECT state, activated_at, released_at, cancelled_at, blocked_reason FROM path_claims WHERE id = %s",
        (claim_id,),
    ).fetchone()
    targets = sorted(
        r[0]
        for r in conn.execute(
            "SELECT pt.path_string FROM path_claim_targets pct JOIN path_targets pt ON pt.id = pct.target_id WHERE pct.claim_id = %s",
            (claim_id,),
        ).fetchall()
    )
    amend_count = conn.execute(
        "SELECT COUNT(*) FROM path_claim_amendments WHERE claim_id = %s", (claim_id,)
    ).fetchone()[0]
    return (tuple(pc) if pc else None, targets, int(amend_count))


@pytest.fixture
def patch_conn(monkeypatch, conn):
    """Force every dispatch surface to operate on the in-memory test conn."""

    class _NoCloseConn:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, *a, **kw):
            return self._inner.execute(*a, **kw)

        def executemany(self, *a, **kw):
            return self._inner.executemany(*a, **kw)

        def commit(self):
            return self._inner.commit()

        def close(self):
            return None

    wrapper = _NoCloseConn(conn)
    monkeypatch.setattr(path_claims_dispatch, "_open_conn", lambda: wrapper)
    ok = type("BoundaryOK", (), {"to_dict": lambda self: {"status": "valid"}})
    monkeypatch.setattr(
        path_claims_dispatch, "boundary_check_for_claim", lambda *a, **kw: ok()
    )
    monkeypatch.setattr(path_claims_dispatch_amend, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_narrow, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_state, "open_conn", lambda: wrapper)
    return conn


@pytest.fixture
def staged(patch_conn):
    """Seed item, holder + intruder sessions, work_claim, and a path_claim."""
    actor = local_human(patch_conn)
    seed_item(patch_conn)
    foo = seed_target(patch_conn, path_string="src/foo.py")
    bar = seed_target(patch_conn, path_string="src/bar.py")
    seed_session(patch_conn, HOLDER_SESSION)
    seed_session(patch_conn, INTRUDER_SESSION)
    seed_work_claim(patch_conn, session_id=HOLDER_SESSION)
    claim_id = seed_path_claim(patch_conn, actor_id=actor, target_ids=(foo, bar))
    patch_conn.commit()
    return {"conn": patch_conn, "actor": actor, "claim_id": claim_id}


def err_payload(capsys):
    """Drain capsys; assert stdout empty; parse the structured stderr payload."""
    out, err = capsys.readouterr()
    assert out == ""
    return json.loads(err.strip())
