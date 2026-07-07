"""raw_query must acquire its connection through the connected-env readiness
boundary (``db_backend.connect_psycopg``), not a bare ``psycopg.connect`` —
that is what lets ``YOKE_ENV=<env> db_router query`` self-heal a dead
tunnel instead of surfacing a raw connection-refused.

Kept separate from ``test_raw_query`` (at the authored-line cap).
"""

from __future__ import annotations

import io

from yoke_core.cli import raw_query
from yoke_core.domain import connected_env_readiness as cer
from yoke_core.domain import db_backend


class _FakeCursor:
    description = [("one",)]

    def fetchall(self):
        return [(1,)]


class _FakeConn:
    def __init__(self, log: list[str]):
        self._log = log

    def execute(self, sql):
        self._log.append(f"execute:{sql}")
        return _FakeCursor()

    def commit(self):
        self._log.append("commit")

    def rollback(self):
        self._log.append("rollback")

    def close(self):
        self._log.append("close")


def test_execute_query_opens_via_readiness_boundary(monkeypatch):
    log: list[str] = []

    def fake_connect_psycopg(*args, **kwargs):
        log.append("connect_psycopg")
        return _FakeConn(log)

    monkeypatch.setattr(db_backend, "connect_psycopg", fake_connect_psycopg)
    out, err = io.StringIO(), io.StringIO()

    rc = raw_query.execute_query("SELECT 1", out=out, err=err)

    assert rc == 0
    assert out.getvalue() == "1\n"
    assert log == ["connect_psycopg", "execute:SELECT 1", "commit", "close"]


def test_execute_query_surfaces_heal_failure_loudly(monkeypatch):
    def fake_connect_psycopg(*args, **kwargs):
        raise cer.ConnectedEnvUnavailable(
            "connected-env Postgres is still unreachable after tunnel "
            "self-heal: probe failed"
        )

    monkeypatch.setattr(db_backend, "connect_psycopg", fake_connect_psycopg)
    out, err = io.StringIO(), io.StringIO()

    rc = raw_query.execute_query("SELECT 1", out=out, err=err)

    assert rc == 1
    assert out.getvalue() == ""
    assert "Error:" in err.getvalue()
    assert "self-heal" in err.getvalue()
