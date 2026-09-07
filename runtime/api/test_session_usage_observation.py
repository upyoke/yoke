"""Storing a consumption reading without ever unlearning a total."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    ModelUsage,
    SessionUsage,
    unavailable,
    usage_document,
)
from yoke_core.domain.session_usage_observation import (
    USAGE_COLUMN,
    observed_usage_document,
    record_session_usage,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE harness_sessions ("
        "session_id TEXT PRIMARY KEY, usage_totals TEXT DEFAULT NULL)"
    )
    connection.execute("INSERT INTO harness_sessions (session_id) VALUES ('session-1')")
    connection.commit()
    return connection


def _stored(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        f"SELECT {USAGE_COLUMN} FROM harness_sessions WHERE session_id='session-1'"
    ).fetchone()
    return row[0]


def _reading(tokens: int) -> str:
    return usage_document(
        SessionUsage(
            status=USAGE_COMPLETE,
            source="transcript assistant message.usage",
            models=(ModelUsage(model="claude-opus-5", input=tokens),),
        )
    )


def _payload(document: str | None) -> str:
    body: dict[str, object] = {"session_id": "session-1"}
    if document is not None:
        body[USAGE_COLUMN] = document
    return json.dumps(body)


def test_a_measured_reading_is_stored(conn: sqlite3.Connection) -> None:
    assert record_session_usage(
        conn, session_id="session-1", payload_json=_payload(_reading(100))
    )

    assert json.loads(_stored(conn))["models"][0]["input"] == 100


def test_a_later_reading_replaces_rather_than_adds(conn: sqlite3.Connection) -> None:
    """Every reading is cumulative, so a newer one is a better answer."""
    record_session_usage(
        conn, session_id="session-1", payload_json=_payload(_reading(100))
    )

    record_session_usage(
        conn, session_id="session-1", payload_json=_payload(_reading(400))
    )

    assert json.loads(_stored(conn))["models"][0]["input"] == 400


def test_an_identical_reading_is_write_free(conn: sqlite3.Connection) -> None:
    payload = _payload(_reading(100))
    record_session_usage(conn, session_id="session-1", payload_json=payload)

    assert not record_session_usage(conn, session_id="session-1", payload_json=payload)


def test_an_unavailable_reading_never_erases_a_measured_total(
    conn: sqlite3.Connection,
) -> None:
    record_session_usage(
        conn, session_id="session-1", payload_json=_payload(_reading(100))
    )

    record_session_usage(
        conn,
        session_id="session-1",
        payload_json=_payload(usage_document(unavailable("artifact went away"))),
    )

    assert json.loads(_stored(conn))["models"][0]["input"] == 100


def test_an_unavailable_reading_records_its_reason_when_nothing_is_stored(
    conn: sqlite3.Connection,
) -> None:
    """The reason is what an operator reads in place of a total."""
    record_session_usage(
        conn,
        session_id="session-1",
        payload_json=_payload(usage_document(unavailable("this harness counts none"))),
    )

    assert json.loads(_stored(conn))["reason"] == "this harness counts none"


def test_a_payload_carrying_no_reading_and_no_executor_writes_nothing(
    conn: sqlite3.Connection,
) -> None:
    assert not record_session_usage(
        conn, session_id="session-1", payload_json=_payload(None)
    )
    assert _stored(conn) is None


def test_an_unknown_session_is_not_inserted(conn: sqlite3.Connection) -> None:
    assert not record_session_usage(
        conn, session_id="absent", payload_json=_payload(_reading(100))
    )


def test_a_relayed_reading_is_preferred_over_reading_the_artifact_here() -> None:
    """The relaying machine is the one that can see the artifact."""
    document = _reading(100)

    assert observed_usage_document(_payload(document), "claude-code") == document


def test_a_local_payload_without_a_reading_takes_one_from_the_artifact(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yoke_cli.config import machine_config

    home = tmp_path / "yoke-home"
    home.mkdir()
    monkeypatch.setattr(machine_config, "yoke_home", lambda: home)
    transcript = tmp_path / "s.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_a",
                    "model": "claude-opus-5",
                    "usage": {"input_tokens": 7, "output_tokens": 3},
                },
            }
        )
        + "\n"
    )
    payload = json.dumps(
        {"session_id": "session-1", "transcript_path": str(transcript)}
    )

    document = observed_usage_document(payload, "claude-code")

    assert json.loads(document)["models"][0]["input"] == 7
