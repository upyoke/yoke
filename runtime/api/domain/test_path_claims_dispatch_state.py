"""Coverage for path-claim activation / terminal dispatcher commands."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import path_claims_dispatch, path_claims_dispatch_state
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP, ambient_holder_session, conn, local_human, seed_target,
    seed_test_holder_for,
)


def _seed_item(conn, *, item_id: int = 9001) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    seed_test_holder_for(conn, item_id=item_id)
    conn.commit()
    return item_id


@pytest.fixture
def patch_conn(monkeypatch, conn, ambient_holder_session):  # noqa: F811
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
    monkeypatch.setattr(path_claims_dispatch_state, "open_conn", lambda: wrapper)
    return conn


def _capture(capsys):
    captured = capsys.readouterr()
    return captured.out, captured.err


def _registered_claim_id(conn, capsys) -> int:
    actor = local_human(conn)
    item_id = _seed_item(conn)
    seed_target(conn, path_string="runtime/api/domain")
    path_claims_dispatch.cmd_register(
        [
            "--item",
            str(item_id),
            "--integration-target",
            "main",
            "--paths",
            "runtime/api/domain",
            "--actor-id",
            str(actor),
        ]
    )
    out, _ = _capture(capsys)
    return int(json.loads(out.strip())["claim"]["id"])


class TestStateCommands:
    def test_activate_transitions_to_active(self, patch_conn, capsys):
        claim_id = _registered_claim_id(patch_conn, capsys)
        rc = path_claims_dispatch.cmd_activate(
            [str(claim_id), "--base-commit-sha", SNAP]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        claim = json.loads(out.strip())["claim"]
        assert claim["state"] == "active"
        assert claim["base_commit_sha"] == SNAP

    def test_release_transitions_to_released(self, patch_conn, capsys):
        claim_id = _registered_claim_id(patch_conn, capsys)
        rc = path_claims_dispatch.cmd_release(
            [str(claim_id), "--reason", "merged"]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        claim = json.loads(out.strip())["claim"]
        assert claim["state"] == "released"
        assert claim["release_reason"] == "merged"

    def test_cancel_transitions_to_cancelled(self, patch_conn, capsys):
        claim_id = _registered_claim_id(patch_conn, capsys)
        rc = path_claims_dispatch.cmd_cancel(
            [str(claim_id), "--reason", "abandoned"]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        claim = json.loads(out.strip())["claim"]
        assert claim["state"] == "cancelled"
        assert claim["cancel_reason"] == "abandoned"
