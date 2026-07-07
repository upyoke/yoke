"""Tests for done-transition path-snapshot prewarming."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.engines import done_transition_snapshot


class _Rows:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self):
        self.closed = False
        self.queries = []

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        return _Rows((1,))

    def close(self):
        self.closed = True


def test_ensure_snapshot_uses_backend_connection(monkeypatch):
    conn = _Conn()
    calls = {}

    from yoke_core.domain import db_helpers, path_snapshots, project_checkout_locations

    monkeypatch.setattr(db_helpers, "connect", lambda: conn)
    monkeypatch.setattr(
        project_checkout_locations,
        "checkout_for_project_id",
        lambda project_id: "/repo/root",
    )
    monkeypatch.setattr(
        done_transition_snapshot.subprocess,
        "run",
        lambda cmd, **_kwargs: calls.setdefault(
            "git", (cmd, SimpleNamespace(returncode=0, stdout="abc123\n"))
        )[1],
    )
    monkeypatch.setattr(
        path_snapshots,
        "ensure_snapshot_at",
        lambda c, project, head: calls.setdefault(
            "snapshot", (c, project, head)
        ),
    )

    done_transition_snapshot.ensure_snapshot_for_item(42)

    assert conn.queries == [
        (
            "SELECT project_id FROM items "
            "WHERE id = %s",
            (42,),
        )
    ]
    assert calls["git"][0] == ["git", "-C", "/repo/root", "rev-parse", "HEAD"]
    assert calls["snapshot"] == (conn, 1, "abc123")
    assert conn.closed is True
