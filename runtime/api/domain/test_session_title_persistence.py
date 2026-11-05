"""A client settles a title only after the durable row confirms it."""

import sqlite3
from types import SimpleNamespace

from yoke_contracts.hook_runner.client_facts import HARNESS_TITLE_KEY, client_fact
from yoke_core.hooks import session_title


def test_title_write_confirmation_and_clear(tmp_path, monkeypatch):
    database = tmp_path / "sessions.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            "CREATE TABLE harness_sessions(session_id TEXT PRIMARY KEY,harness_title TEXT); INSERT INTO harness_sessions VALUES ('chat',NULL);"
        )
    monkeypatch.setattr(session_title, "connect", lambda: sqlite3.connect(database))
    payload = client_fact(HARNESS_TITLE_KEY, "[PILLS]")
    assert session_title.confirmed_title("chat", payload) is None
    session_title.evaluate(SimpleNamespace(session_id="chat", payload=payload))
    assert session_title.confirmed_title("chat", payload) == {"value": "[PILLS]"}
    renamed = client_fact(HARNESS_TITLE_KEY, "Renamed")
    assert session_title.confirmed_title("chat", renamed) is None
    session_title.evaluate(SimpleNamespace(session_id="chat", payload=renamed))
    assert session_title.confirmed_title("chat", renamed) == {"value": "Renamed"}
    cleared = client_fact(HARNESS_TITLE_KEY, None)
    session_title.evaluate(SimpleNamespace(session_id="chat", payload=cleared))
    assert session_title.confirmed_title("chat", cleared) == {"value": None}
    assert session_title.confirmed_title("missing", payload) is None


def test_absent_or_malformed_fact_cannot_clear_title(tmp_path, monkeypatch):
    database = tmp_path / "sessions.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            "CREATE TABLE harness_sessions(session_id TEXT PRIMARY KEY,harness_title TEXT); INSERT INTO harness_sessions VALUES ('chat','Keep');"
        )
    monkeypatch.setattr(session_title, "connect", lambda: sqlite3.connect(database))
    for payload in (
        {},
        {HARNESS_TITLE_KEY: {"schema": 1}},
        client_fact(HARNESS_TITLE_KEY, 12),
    ):
        session_title.evaluate(SimpleNamespace(session_id="chat", payload=payload))
    assert session_title.confirmed_title(
        "chat", client_fact(HARNESS_TITLE_KEY, "Keep")
    ) == {"value": "Keep"}
