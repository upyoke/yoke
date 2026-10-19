"""A local Codex observation keeps reading effort after the model is stored."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import Mock

import pytest

from yoke_contracts.session_model_facts import NOT_REPORTED_EFFORT, SessionModelFacts
from yoke_core.domain.model_reference_store import (
    create_model_reference_table,
    seed_initial_catalog,
)
from yoke_core.domain.session_identity_observation import (
    ROW_COLUMNS,
    record_session_identity,
)
from yoke_core.domain.universe_levels import create_universe_settings_table

SESSION = "01a05895-484b-7ab2-b3b2-5b88a84df583"
PAYLOAD = json.dumps({"session_id": SESSION, "model": "gpt-6-astra"})


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    columns = ", ".join(f"{column} TEXT DEFAULT NULL" for column in ROW_COLUMNS)
    connection.execute(
        "CREATE TABLE harness_sessions ("
        "session_id TEXT PRIMARY KEY, ended_at TEXT DEFAULT NULL, "
        f"executor TEXT, project_id INTEGER, execution_level TEXT, {columns})"
    )
    create_universe_settings_table(connection)
    create_model_reference_table(connection)
    seed_initial_catalog(connection)
    connection.execute(
        "INSERT INTO harness_sessions (session_id, model, executor_surface) "
        "VALUES (?, 'gpt-6-astra', 'codex-desktop')",
        (SESSION,),
    )
    connection.commit()
    return connection


@pytest.fixture
def rollout_reads(monkeypatch: pytest.MonkeyPatch) -> Mock:
    reads = Mock()
    monkeypatch.setattr("yoke_harness.hooks.identity_relay.resolve_model_facts", reads)
    return reads


def _stored(conn: sqlite3.Connection, column: str) -> str | None:
    return conn.execute(
        f"SELECT {column} FROM harness_sessions WHERE session_id=?", (SESSION,)
    ).fetchone()[0]


def _observe(conn: sqlite3.Connection) -> bool:
    return record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=PAYLOAD,
        executor="codex",
        local_evaluation=True,
    )


def test_a_stored_model_does_not_stop_reading_the_rollouts_effort(
    conn, rollout_reads
) -> None:
    rollout_reads.return_value = SessionModelFacts(
        model="gpt-6-astra", reasoning_effort="xhigh"
    )
    assert _observe(conn)
    assert _stored(conn, "reasoning_effort") == "xhigh"

    rollout_reads.return_value = SessionModelFacts(
        model="gpt-6-astra", reasoning_effort="low"
    )
    assert _observe(conn)
    assert _stored(conn, "reasoning_effort") == "low"


def test_a_rollout_with_no_effort_places_the_session_at_the_lowest_level(
    conn, rollout_reads
) -> None:
    rollout_reads.return_value = SessionModelFacts(
        model="gpt-6-astra", reasoning_effort=NOT_REPORTED_EFFORT
    )

    assert _observe(conn)

    assert _stored(conn, "reasoning_effort") == NOT_REPORTED_EFFORT
    assert _stored(conn, "execution_level") == "INTERN"


def test_a_relayed_not_reported_reading_is_stored_as_carried(conn) -> None:
    payload = json.dumps(
        {
            "session_id": SESSION,
            "model": "gpt-6-astra",
            "reasoning_effort": "not_reported",
        }
    )

    assert record_session_identity(
        conn, session_id=SESSION, payload_json=payload, executor="codex"
    )

    assert _stored(conn, "reasoning_effort") == NOT_REPORTED_EFFORT
