# ruff: noqa: F811
"""Shared fixtures for the ``path-claims`` CLI dispatcher tests.

The dispatcher opens the canonical DB through
:func:`yoke_core.domain.db_helpers.connect`; ``patch_conn`` points every
dispatcher surface at the in-memory test connection instead.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import (
    path_claims_dispatch,
    path_claims_dispatch_amend,
    path_claims_dispatch_state,
)
from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    ambient_holder_session,
    conn,
    seed_test_holder_for,
)


def seed_item(conn, *, item_id: int = 9001, project: str = "yoke") -> int:
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
        "VALUES (%s, 'item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    seed_test_holder_for(conn, item_id=item_id)
    conn.commit()
    return item_id


def seed_session(conn, session_id: str) -> str:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "project_id, execution_level, executor_version, machine_id, workspace, mode, offered_at, "
        "last_heartbeat) "
        "VALUES (%s, 'claude-code', 'test', 'test', 1, 'primary', NULL, NULL, '/tmp', 'wait', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
        (session_id,),
    )
    conn.commit()
    return session_id


@pytest.fixture
def patch_conn(monkeypatch, conn, ambient_holder_session):  # noqa: F811
    """Use the in-memory conn for every dispatcher surface; pin ambient holder."""

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
    monkeypatch.setattr(path_claims_dispatch_amend, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_state, "open_conn", lambda: wrapper)
    return conn


def capture(capsys):
    captured = capsys.readouterr()
    return captured.out, captured.err
