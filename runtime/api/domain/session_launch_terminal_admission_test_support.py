# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.session_launch_itemless_test_support import _request as _request

from copy import deepcopy

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition

from yoke_core.domain.handlers import session_launch as handlers

from yoke_core.domain.session_launch_assignment import (
    assigned_item_id,
    refuse_terminal_assigned_item,
)

from yoke_core.domain.session_launch_types import SessionLaunchError

from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
)


class _NoCloseConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def _pin_definition() -> dict:
    return deepcopy(builtin_workflow_definition("dash")["definition"])


def _seed_pinned_item(
    conn,
    *,
    status: str,
    workflow_id: str = "dash",
    definition: dict | None = None,
    sequence: int = 41,
) -> str:
    payload = definition if definition is not None else _pin_definition()
    conn.execute("ALTER TABLE projects ADD COLUMN org_id INTEGER DEFAULT 1")
    conn.execute("ALTER TABLE projects ADD COLUMN name TEXT DEFAULT 'Launch'")
    conn.execute("ALTER TABLE projects ADD COLUMN public_item_prefix TEXT")
    conn.execute("UPDATE projects SET public_item_prefix='LP' WHERE id=10")
    conn.execute(
        "CREATE TABLE workflow_versions ("
        "id INTEGER PRIMARY KEY, workflow_id TEXT NOT NULL, version INTEGER, "
        "definition_json TEXT NOT NULL, definition_digest TEXT NOT NULL)"
    )
    conn.execute("DROP TABLE items")
    conn.execute(
        "CREATE TABLE items ("
        "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
        "project_sequence INTEGER NOT NULL, title TEXT, status TEXT NOT NULL, "
        "workflow_id TEXT NOT NULL, workflow_version_id INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO workflow_versions "
        "(id, workflow_id, version, definition_json, definition_digest) "
        "VALUES (1, ?, 1, ?, ?)",
        (
            workflow_id,
            canonical_definition_json(payload),
            definition_digest(payload),
        ),
    )
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, project_sequence, title, status, "
        "workflow_id, workflow_version_id) "
        "VALUES (41, 10, ?, 'Active launch target', ?, ?, 1)",
        (sequence, status, workflow_id),
    )
    conn.commit()
    return f"LP-{sequence}"


def _wire_create(monkeypatch, conn) -> None:
    # This fixture tests launch admission; instruction delivery has its own suite.
    monkeypatch.setattr(
        "yoke_core.domain.workflow_execution_instructions.resolve_for_item",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(
        handlers, "launch_authorization", lambda *_a, **_k: authorization()
    )
    monkeypatch.setattr("yoke_core.domain.session_launch_requests.utc_now", lambda: NOW)
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_surface_selection.utc_now",
        lambda: NOW,
    )


def _create_payload(item: str, *, compose_mandate: bool, key: str) -> dict:
    return {
        "project": "launch-project",
        "item": item,
        "executor_surface": "codex-cli",
        "model": "gpt-6.1-sol",
        "reasoning_effort": "medium",
        "instructions": "Custom full body." if not compose_mandate else "",
        "idempotency_key": key,
        "compose_mandate": compose_mandate,
    }


def _write_counts(conn) -> tuple[int, int, int]:
    launches = conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0]
    messages = conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0]
    attempts = conn.execute("SELECT COUNT(*) FROM session_launch_attempts").fetchone()[
        0
    ]
    return int(launches), int(messages), int(attempts)


def _create_conn(monkeypatch, *, status: str, definition: dict | None = None):
    from runtime.api.domain.session_launch_level_test_support import (
        CODEX_SOL,
        level_connection,
    )

    conn = level_connection(CODEX_SOL)
    add_relay(conn, connected_until="2026-08-24T12:00:00Z")
    item = _seed_pinned_item(conn, status=status, definition=definition)
    _wire_create(monkeypatch, conn)
    return conn, item
