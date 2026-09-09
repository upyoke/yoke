"""Filling a session's served identity from evidence that arrives at the end."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from yoke_core.domain.session_identity_observation import (
    ROW_COLUMNS,
    SURFACE_COLUMN,
    observed_surface,
    record_session_identity,
)


SESSION = "session-1"


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    columns = ", ".join(f"{column} TEXT DEFAULT NULL" for column in ROW_COLUMNS)
    connection.execute(
        "CREATE TABLE harness_sessions ("
        f"session_id TEXT PRIMARY KEY, ended_at TEXT DEFAULT NULL, {columns})"
    )
    connection.execute(
        "INSERT INTO harness_sessions (session_id) VALUES (?)", (SESSION,)
    )
    connection.commit()
    return connection


def _stored(conn: sqlite3.Connection, column: str) -> str | None:
    row = conn.execute(
        f"SELECT {column} FROM harness_sessions WHERE session_id=?", (SESSION,)
    ).fetchone()
    return row[0]


def _claude_transcript(tmp_path: Path, model: str = "claude-opus-5") -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        json.dumps(
            {"type": "assistant", "effort": "high", "message": {"model": model}}
        )
        + "\n",
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def local_claude(monkeypatch, tmp_path) -> None:
    """A machine whose own Claude surface is the only identity authority."""
    from yoke_cli.config import machine_config

    monkeypatch.setattr(machine_config, "yoke_home", lambda: tmp_path / "yoke-home")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CURSOR_TRANSCRIPT_PATH", raising=False)
    monkeypatch.delenv("CURSOR_INVOKED_AS", raising=False)


def _payload(**fields: object) -> str:
    return json.dumps({"session_id": SESSION, **fields})


def test_a_local_turn_that_called_no_tool_still_records_what_it_was_served(
    conn, local_claude, tmp_path
) -> None:
    payload = _payload(transcript_path=_claude_transcript(tmp_path))

    assert record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=payload,
        executor="claude-code",
        local_evaluation=True,
    )

    assert _stored(conn, "model") == "claude-opus-5"
    assert _stored(conn, "reasoning_effort") == "high"
    assert _stored(conn, SURFACE_COLUMN) == "claude-cli"


def test_evidence_that_proves_nothing_writes_nothing(conn, monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CURSOR_TRANSCRIPT_PATH", raising=False)
    monkeypatch.delenv("CURSOR_INVOKED_AS", raising=False)

    assert not record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(transcript_path="/nonexistent/transcript.jsonl"),
        executor="claude-code",
        local_evaluation=True,
    )

    assert _stored(conn, "model") is None
    assert _stored(conn, SURFACE_COLUMN) is None


def test_observing_the_same_finished_turn_again_is_write_free(
    conn, local_claude, tmp_path
) -> None:
    payload = _payload(transcript_path=_claude_transcript(tmp_path))
    assert record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=payload,
        executor="claude-code",
        local_evaluation=True,
    )

    assert not record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=payload,
        executor="claude-code",
        local_evaluation=True,
    )


def test_an_ended_session_records_its_identity_without_being_revived(
    conn, local_claude, tmp_path
) -> None:
    conn.execute(
        "UPDATE harness_sessions SET ended_at='2026-09-09T05:00:00Z' "
        "WHERE session_id=?",
        (SESSION,),
    )
    conn.commit()

    assert record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(transcript_path=_claude_transcript(tmp_path)),
        executor="claude-code",
        local_evaluation=True,
    )

    assert _stored(conn, "model") == "claude-opus-5"
    assert _stored(conn, "ended_at") == "2026-09-09T05:00:00Z"


def test_the_ask_is_never_written_by_a_reader_of_what_was_served(conn) -> None:
    conn.execute(
        "UPDATE harness_sessions SET requested_model='claude-opus-5[1m]' "
        "WHERE session_id=?",
        (SESSION,),
    )
    conn.commit()

    record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(model="claude-sonnet-5", requested_model="gpt-test"),
        executor="claude-code",
    )

    assert _stored(conn, "model") == "claude-sonnet-5"
    assert _stored(conn, "requested_model") == "claude-opus-5[1m]"


def test_a_stored_surface_is_never_replaced_by_a_later_reader(conn) -> None:
    conn.execute(
        f"UPDATE harness_sessions SET {SURFACE_COLUMN}='claude-desktop' "
        "WHERE session_id=?",
        (SESSION,),
    )
    conn.commit()

    record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(model="claude-opus-5", entrypoint="cli"),
        executor="claude-code",
    )

    assert _stored(conn, SURFACE_COLUMN) == "claude-desktop"


def test_a_session_with_no_row_is_never_created(conn) -> None:
    assert not record_session_identity(
        conn,
        session_id="never-registered",
        payload_json=json.dumps({"session_id": "never-registered", "model": "m"}),
        executor="claude-code",
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM harness_sessions").fetchone()[0] == 1
    )


@pytest.mark.parametrize("token", ["banana", "skill", ""])
def test_a_token_no_harness_registry_recognizes_stays_unknown(token: str) -> None:
    assert observed_surface({"entrypoint": token}, "codex") is None


@pytest.fixture
def local_probes_refuse(monkeypatch):
    """Fail loudly if a relayed evaluation reaches for this machine's own facts."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("a relayed evaluation read this machine's identity")

    monkeypatch.setattr(
        "yoke_harness.hooks.identity_relay.resolve_model_facts", refuse
    )
    monkeypatch.setattr("yoke_harness.hooks.identity_relay.client_entrypoint", refuse)


def test_a_relayed_payload_that_named_nothing_leaves_the_row_unknown(
    conn, local_probes_refuse, local_claude
) -> None:
    """The client's session does not run here, so this machine cannot answer for it."""
    assert not record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(transcript_path="/some/other/machine/transcript.jsonl"),
        executor="claude-code",
    )

    assert _stored(conn, "model") is None
    assert _stored(conn, SURFACE_COLUMN) is None


def test_a_relayed_payload_still_stores_every_fact_it_did_carry(
    conn, local_probes_refuse, local_claude
) -> None:
    assert record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(model="claude-opus-5", entrypoint="claude-desktop"),
        executor="claude-code",
    )

    assert _stored(conn, "model") == "claude-opus-5"
    assert _stored(conn, SURFACE_COLUMN) == "claude-desktop"


def test_a_relayed_payload_carrying_only_a_model_leaves_the_surface_unknown(
    conn, local_probes_refuse, local_claude
) -> None:
    assert record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(model="claude-opus-5"),
        executor="claude-code",
    )

    assert _stored(conn, "model") == "claude-opus-5"
    assert _stored(conn, SURFACE_COLUMN) is None


def test_a_relayed_model_switch_still_replaces_the_stored_one(
    conn, local_probes_refuse
) -> None:
    conn.execute(
        "UPDATE harness_sessions SET model='claude-opus-5' WHERE session_id=?",
        (SESSION,),
    )
    conn.commit()

    assert record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(model="claude-sonnet-5"),
        executor="claude-code",
    )

    assert _stored(conn, "model") == "claude-sonnet-5"


def test_a_local_session_that_already_named_a_model_reads_no_artifact_again(
    conn, local_probes_refuse, local_claude, tmp_path
) -> None:
    """The tool-call refresher owns a live local session's model switches."""
    conn.execute(
        "UPDATE harness_sessions SET model='claude-opus-5', "
        f"{SURFACE_COLUMN}='claude-cli' WHERE session_id=?",
        (SESSION,),
    )
    conn.commit()

    assert not record_session_identity(
        conn,
        session_id=SESSION,
        payload_json=_payload(transcript_path=_claude_transcript(tmp_path)),
        executor="claude-code",
        local_evaluation=True,
    )
