"""A client settles a title only after the durable row confirms it."""

import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from yoke_contracts.hook_runner.client_facts import HARNESS_TITLE_KEY, client_fact
from yoke_core.hooks import session_title

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.test_api_hooks_evaluate_route import _request_body


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


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


def test_desktop_title_survives_real_hook_route_and_confirms(
    hooks_db, tmp_path, monkeypatch
):
    from yoke_core.domain import db_helpers
    from yoke_harness.hooks import client_facts, client_session_title

    monkeypatch.setattr(
        client_session_title.machine_config,
        "effective_temp_root",
        lambda: str(tmp_path / "cache"),
    )
    session = str(uuid4())
    transcript = tmp_path / "chat.jsonl"
    payload = {
        "session_id": session,
        "identity_stamped": True,
        "cwd": str(tmp_path),
        "transcript_path": str(transcript),
    }
    with _client_for_db(hooks_db["db_path"]) as client:
        for event, title in [
            ("SessionStart", "Native chat"),
            ("UserPromptSubmit", "Renamed chat"),
        ]:
            transcript.write_text(
                json.dumps({"type": "custom-title", "customTitle": title})
            )
            facts = client_facts.collect_client_facts(
                event,
                payload,
                "claude-desktop",
                client_facts.event_chain(event, payload),
            )
            response = client.post(
                "/v1/hooks/evaluate",
                json=_request_body(
                    event_name=event,
                    executor="claude-desktop",
                    stdin=json.dumps(payload),
                    payload_extra=facts,
                ),
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["harness_title_confirmation"] == {"value": title}, json.dumps(
                result, indent=2
            )
            with db_helpers.connect() as conn:
                row = conn.execute(
                    "SELECT harness_title FROM harness_sessions WHERE session_id=%s",
                    (session,),
                ).fetchone()
                assert row is not None and row[0] == title
            client_session_title.confirm_title(
                payload, "claude-desktop", result["harness_title_confirmation"]
            )
            assert HARNESS_TITLE_KEY not in client_facts.collect_client_facts(
                event,
                payload,
                "claude-desktop",
                client_facts.event_chain(event, payload),
            )
