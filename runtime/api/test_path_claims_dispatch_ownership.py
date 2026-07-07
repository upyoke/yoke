"""Coverage for ambient item ownership on path-claim mutations.

Mutating ``path-claims`` subcommands must refuse non-holder sessions.
Read-only subcommands remain callable for coordination inspection.
The guard reads the ambient harness session from the env-var chain.
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
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn, local_human, seed_target,
)
from yoke_core.api.service_client_path_claims import cmd_path_claim_widen


HOLDER_SESSION = "sess-holder-ownership"
INTRUDER_SESSION = "sess-intruder-ownership"
ITEM_ID = 9001


def _seed_item(conn, *, item_id=ITEM_ID, project="yoke"):
    project_key = str(project)
    project_id = 2 if project_key == "buzz" else int(project_key) if project_key.isdigit() else 1
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 't', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )


def _seed_session(conn, session_id):
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, "
        "model, project_id, execution_lane, capabilities, workspace, mode, "
        "offered_at, last_heartbeat) "
        "VALUES (%s, 'test', 'test', 'test', 1, 'primary', '[]', '/tmp', "
        "'active', '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
        (session_id,),
    )


def _seed_work_claim(conn, *, session_id, item_id=ITEM_ID):
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id, "
        "claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, '2026-05-01T00:00:00Z', "
        "'2026-05-01T00:00:00Z')",
        (session_id, item_id),
    )


def _seed_path_claim(conn, *, actor_id, item_id=ITEM_ID, target_ids=()):
    cur = conn.execute(
        "INSERT INTO path_claims (state, mode, actor_id, item_id, "
        "integration_target, registered_at) "
        "VALUES ('planned', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z') RETURNING id",
        (actor_id, item_id),
    )
    claim_id = int(cur.fetchone()[0])
    for tid in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
            "VALUES (%s, %s, '2026-05-01T00:00:00Z')", (claim_id, tid),
        )
    return claim_id


def _projection_snapshot(conn, claim_id):
    pc = conn.execute(
        "SELECT state, activated_at, released_at, cancelled_at, "
        "blocked_reason FROM path_claims WHERE id = %s",
        (claim_id,),
    ).fetchone()
    targets = sorted(
        r[0] for r in conn.execute(
            "SELECT pt.path_string FROM path_claim_targets pct "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            "WHERE pct.claim_id = %s",
            (claim_id,),
        ).fetchall()
    )
    amend_count = conn.execute(
        "SELECT COUNT(*) FROM path_claim_amendments WHERE claim_id = %s",
        (claim_id,),
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
        path_claims_dispatch, "boundary_check_for_claim",
        lambda *a, **kw: ok(),
    )
    monkeypatch.setattr(path_claims_dispatch_amend, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_narrow, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_state, "open_conn", lambda: wrapper)
    return conn


@pytest.fixture
def staged(patch_conn):
    """Seed item, holder + intruder sessions, work_claim, and a path_claim."""
    actor = local_human(patch_conn)
    _seed_item(patch_conn)
    foo = seed_target(patch_conn, path_string="src/foo.py")
    bar = seed_target(patch_conn, path_string="src/bar.py")
    _seed_session(patch_conn, HOLDER_SESSION)
    _seed_session(patch_conn, INTRUDER_SESSION)
    _seed_work_claim(patch_conn, session_id=HOLDER_SESSION)
    claim_id = _seed_path_claim(
        patch_conn, actor_id=actor, target_ids=(foo, bar),
    )
    patch_conn.commit()
    return {"conn": patch_conn, "actor": actor, "claim_id": claim_id}


def _err_payload(capsys):
    """Drain capsys; assert stdout empty; parse the structured stderr payload."""
    out, err = capsys.readouterr()
    assert out == ""
    return json.loads(err.strip())


class TestRegister:
    def test_register_denied_for_non_holder(
        self, staged, monkeypatch, capsys,
    ):
        conn = staged["conn"]
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)
        before_claims = conn.execute(
            "SELECT COUNT(*) FROM path_claims"
        ).fetchone()[0]
        before_targets = conn.execute(
            "SELECT COUNT(*) FROM path_claim_targets"
        ).fetchone()[0]

        rc = path_claims_dispatch.cmd_register([
            "--item", f"YOK-{ITEM_ID}",
            "--integration-target", "main",
            "--paths", "src/foo.py",
            "--actor-id", str(staged["actor"]),
        ])
        payload = _err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["item_id"] == ITEM_ID
        assert payload["caller_session_id"] == INTRUDER_SESSION
        assert payload["holder_session_id"] == HOLDER_SESSION
        assert "claim-work" in payload["recovery"]
        assert payload.get("claim_id") is None
        assert conn.execute(
            "SELECT COUNT(*) FROM path_claims"
        ).fetchone()[0] == before_claims
        assert conn.execute(
            "SELECT COUNT(*) FROM path_claim_targets"
        ).fetchone()[0] == before_targets

    def test_register_session_id_flag_does_not_bypass_guard(
        self, staged, monkeypatch, capsys,
    ):
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)
        rc = path_claims_dispatch.cmd_register([
            "--item", f"YOK-{ITEM_ID}",
            "--integration-target", "main",
            "--paths", "src/foo.py",
            "--actor-id", str(staged["actor"]),
            "--session-id", HOLDER_SESSION,
        ])
        payload = _err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["caller_session_id"] == INTRUDER_SESSION

    def test_register_denied_when_no_work_claim_exists(
        self, patch_conn, monkeypatch, capsys,
    ):
        actor = local_human(patch_conn)
        _seed_item(patch_conn, item_id=9002)
        seed_target(patch_conn, path_string="src/foo.py")
        _seed_session(patch_conn, INTRUDER_SESSION)
        patch_conn.commit()
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)
        rc = path_claims_dispatch.cmd_register([
            "--item", "YOK-9002",
            "--integration-target", "main",
            "--paths", "src/foo.py",
            "--actor-id", str(actor),
        ])
        payload = _err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["holder_session_id"] is None


def _activate(cid):
    return path_claims_dispatch_state.cmd_activate(
        [str(cid), "--base-commit-sha", "deadbeef0001"]
    )


def _release(cid):
    return path_claims_dispatch_state.cmd_release(
        [str(cid), "--reason", "intrude"]
    )


def _cancel(cid):
    return path_claims_dispatch_state.cmd_cancel(
        [str(cid), "--reason", "intrude"]
    )


def _widen(cid):
    return path_claims_dispatch_amend.cmd_widen(
        [str(cid), "--paths", "src/bar.py", "--reason", "intrude"]
    )


def _cancel_amendment(cid):
    return path_claims_dispatch_amend.cmd_cancel_amendment(
        [str(cid), "--amendment-id", "9999", "--reason", "intrude"]
    )


class TestStateAndAmendmentsDeniedForNonHolder:
    @pytest.fixture(autouse=True)
    def _deny_env(self, monkeypatch):
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)

    @pytest.mark.parametrize(
        "call",
        [_activate, _release, _cancel, _widen, _cancel_amendment],
        ids=["activate", "release", "cancel", "widen", "cancel_amendment"],
    )
    def test_mutation_denied_and_state_unchanged(self, staged, capsys, call):
        before = _projection_snapshot(staged["conn"], staged["claim_id"])
        rc = call(staged["claim_id"])
        payload = _err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["claim_id"] == staged["claim_id"]
        assert _projection_snapshot(
            staged["conn"], staged["claim_id"]
        ) == before

    def test_narrow_denied_and_state_unchanged(self, staged, tmp_path, capsys):
        before = _projection_snapshot(staged["conn"], staged["claim_id"])
        rc = path_claims_dispatch_narrow.cmd_narrow([
            str(staged["claim_id"]),
            "--drop-paths", "src/bar.py",
            "--reason", "intrude",
            "--repo-path", str(tmp_path),
        ])
        payload = _err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert _projection_snapshot(
            staged["conn"], staged["claim_id"]
        ) == before


def _get(cid):
    return path_claims_dispatch.cmd_get([str(cid)])


def _list_for_item(_cid):
    return path_claims_dispatch.cmd_list(["--item", f"YOK-{ITEM_ID}"])


def _conflicts(_cid):
    return path_claims_dispatch.cmd_conflicts(["--integration-target", "main"])


def _boundary(cid):
    return path_claims_dispatch.cmd_boundary([str(cid), "--repo-path", "."])


class TestReadOnlyRemainsAllowedForNonHolder:
    @pytest.fixture(autouse=True)
    def _deny_env(self, monkeypatch):
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)

    @pytest.mark.parametrize(
        "call",
        [_get, _list_for_item, _conflicts, _boundary],
        ids=["get", "list", "conflicts", "boundary"],
    )
    def test_read_only_allowed(self, staged, capsys, call):
        rc = call(staged["claim_id"])
        out, _err = capsys.readouterr()
        assert rc == 0
        # Each command emits valid JSON on stdout; just confirm parse succeeds.
        json.loads(out)


class TestServiceClientForwardingObservesGuard:
    def test_path_claim_widen_via_service_client_denied(
        self, staged, monkeypatch, capsys,
    ):
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)
        before = _projection_snapshot(staged["conn"], staged["claim_id"])
        rc = cmd_path_claim_widen([
            str(staged["claim_id"]),
            "--paths", "src/bar.py",
            "--reason", "intrude-via-service-client",
        ])
        payload = _err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["claim_id"] == staged["claim_id"]
        assert payload["caller_session_id"] == INTRUDER_SESSION
        assert payload["holder_session_id"] == HOLDER_SESSION
        assert _projection_snapshot(
            staged["conn"], staged["claim_id"]
        ) == before
