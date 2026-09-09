"""The last hook of a turn records the identity that turn finally proved."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from yoke_core.domain.session_identity_observation import (
    ROW_COLUMNS,
    SURFACE_COLUMN,
)
from yoke_core.hooks import hook_registration_tail, run_tail


SESSION = "s-single-turn"


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    columns = ", ".join(f"{column} TEXT DEFAULT NULL" for column in ROW_COLUMNS)
    connection.execute(
        f"CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, {columns})"
    )
    connection.execute(
        "INSERT INTO harness_sessions (session_id) VALUES (?)", (SESSION,)
    )
    connection.commit()
    return connection


@pytest.mark.parametrize("event_name", ["Stop", "SessionEnd"])
def test_a_terminal_hook_fills_identity_without_registering(
    conn, monkeypatch, tmp_path, event_name: str
) -> None:
    from yoke_cli.config import machine_config

    monkeypatch.setattr(machine_config, "yoke_home", lambda: tmp_path / "yoke-home")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {"type": "assistant", "message": {"model": "claude-opus-5"}}
        )
        + "\n",
        encoding="utf-8",
    )
    payload = {"session_id": SESSION, "transcript_path": str(transcript)}
    context = SimpleNamespace(session_id=SESSION, executor_family="claude-code")

    assert (
        run_tail._ensure_session_request(
            event_name=event_name,
            context=context,
            payload=payload,
            stdin_data="{}",
            controls=None,
            preflight_complete=False,
        )
        is None
    )
    hook_registration_tail.apply_hook_session_tail(
        conn,
        ensure_session=None,
        observed_session=run_tail._observed_session_request(
            context=context, payload=payload, stdin_data="{}"
        ),
    )

    row = conn.execute(
        f"SELECT model, {SURFACE_COLUMN} FROM harness_sessions WHERE session_id=?",
        (SESSION,),
    ).fetchone()
    assert row["model"] == "claude-opus-5"
    assert row[SURFACE_COLUMN] == "claude-cli"
