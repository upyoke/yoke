"""Terminal hooks recover a first prompt whose UserPromptSubmit never landed.

Stage QA for YOK-5351: a real Claude session answered a prompt, its
UserPromptSubmit timed out in the resident before reaching the authority,
and the later Stop and SessionEnd succeeded without recovering the prompt,
so the session read as a probe. These tests drive the real hook route with
the client facts the real collector produces from a transcript.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.api_hooks_evaluate_route_test_support import _request_body
from yoke_contracts.hook_runner.client_facts import FIRST_USER_PROMPT_KEY, client_fact
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.schema_init_columns import apply_harness_session_columns
from yoke_core.domain.schema_init_tables_sessions import create_session_tables
from yoke_core.domain.session_probe import probe_session_sql
from yoke_core.domain import db_helpers
from yoke_harness.hooks import client_facts

PROMPT_AT = "2026-11-17T23:20:41.512Z"


@pytest.fixture()
def hooks_db():
    for db in make_test_db_fixture():
        conn = db_helpers.connect()
        try:
            apply_harness_session_columns(conn)
            create_session_tables(conn)
            conn.commit()
        finally:
            conn.close()
        yield db


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _row(session_id):
    conn = db_helpers.connect()
    try:
        return conn.execute(
            f"SELECT s.*, {probe_session_sql()} AS probe FROM harness_sessions s "
            "WHERE session_id = %s", (session_id,)
        ).fetchone()
    finally:
        conn.close()


def _transcript(tmp_path: Path, sid: str, *, prompt: bool = True) -> Path:
    rows = [
        {"type": "user", "sessionId": sid, "isMeta": True,
         "timestamp": "2026-11-17T23:20:40.000Z",
         "message": {"role": "user", "content": "<command-name>init</command-name>"}},
    ]
    if prompt:
        rows.append(
            {"type": "user", "sessionId": sid, "timestamp": PROMPT_AT,
             "message": {"role": "user", "content": "Reply ok"}}
        )
    rows.append(
        {"type": "assistant", "sessionId": sid, "timestamp": "2026-11-17T23:20:44Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}
    )
    path = tmp_path / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def _hook(client, event, sid, transcript, *, extra=None, executor="claude-code", native=None):
    payload = {
        "session_id": sid,
        "cwd": "/client/repo",
        "project_id": 1,
        "transcript_path": str(transcript),
        **(native or {}),
    }
    if extra is None:
        extra = client_facts.collect_client_facts(
            event, payload, executor, client_facts.event_chain(event, payload)
        )
    body = _request_body(
        executor=executor, stdin=json.dumps(payload), payload_extra=extra
    )
    body["event_name"] = event
    response = client.post("/v1/hooks/evaluate", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["exit_code"] == 0, result
    return result


def _refusals(sid):
    conn = db_helpers.connect()
    try:
        rows = conn.execute(
            "SELECT envelope FROM events WHERE event_name = %s AND session_id = %s",
            ("SessionRegistrationRefused", sid),
        ).fetchall()
    finally:
        conn.close()
    found = []
    for row in rows:
        envelope = row["envelope"]
        envelope = json.loads(envelope) if isinstance(envelope, str) else envelope
        found.append(envelope["context"]["code"])
    return found


@pytest.mark.parametrize("terminal", ["Stop", "SessionEnd"])
def test_lost_prompt_delivery_is_recovered_by_terminal_hook(client, tmp_path, terminal):
    sid = f"lost-prompt-{terminal}"
    transcript = _transcript(tmp_path, sid)
    start = _hook(client, "SessionStart", sid, transcript)
    assert start["registration_outcome"] == "registered"
    # UserPromptSubmit never reaches the authority (resident timeout).
    assert _row(sid)["first_user_prompt_at"] is None
    result = _hook(client, terminal, sid, transcript)
    assert not [m for m in result["degraded"] if "session_prompt_attestation" in m]
    stamped = _row(sid)["first_user_prompt_at"]
    assert parse_instant(stamped) == parse_instant(PROMPT_AT)
    # Replays and later terminal hooks never move the write-once stamp.
    _hook(client, "Stop", sid, transcript)
    _hook(client, "SessionEnd", sid, transcript)
    assert _row(sid)["first_user_prompt_at"] == stamped


def test_prompt_hook_stamp_is_not_moved_by_attestation(client, tmp_path):
    sid = "prompt-delivered"
    transcript = _transcript(tmp_path, sid)
    _hook(client, "SessionStart", sid, transcript)
    _hook(client, "UserPromptSubmit", sid, transcript)
    delivered = _row(sid)["first_user_prompt_at"]
    assert delivered is not None
    _hook(client, "Stop", sid, transcript)
    assert _row(sid)["first_user_prompt_at"] == delivered


def test_ended_row_is_stamped_without_revival(client, tmp_path):
    sid = "ended-before-attestation"
    transcript = _transcript(tmp_path, sid)
    _hook(client, "SessionStart", sid, transcript)
    conn = db_helpers.connect()
    try:
        conn.execute(
            "UPDATE harness_sessions SET ended_at = now() "
            "WHERE session_id = %s",
            (sid,),
        )
        conn.commit()
    finally:
        conn.close()
    before = _row(sid)
    _hook(client, "SessionEnd", sid, transcript)
    after = _row(sid)
    assert parse_instant(after["first_user_prompt_at"]) == parse_instant(PROMPT_AT)
    assert before["ended_at"] is not None
    assert after["ended_at"] == before["ended_at"]


def test_true_probe_stays_unstamped(client, tmp_path):
    sid = "true-probe"
    transcript = _transcript(tmp_path, sid, prompt=False)
    _hook(client, "SessionStart", sid, transcript)
    result = _hook(client, "Stop", sid, transcript)
    assert not [m for m in result["degraded"] if "session_prompt_attestation" in m]
    assert _row(sid)["first_user_prompt_at"] is None


def test_foreign_session_attestation_is_ignored(client, tmp_path):
    sid = "attested-for-another"
    transcript = _transcript(tmp_path, sid)
    _hook(client, "SessionStart", sid, transcript)
    foreign = client_fact(
        FIRST_USER_PROMPT_KEY, {"session_id": "someone-else", "at": PROMPT_AT}
    )
    _hook(client, "Stop", sid, transcript, extra=foreign)
    assert _row(sid)["first_user_prompt_at"] is None


def test_unknown_session_refuses_by_name_and_registers_nothing(client, tmp_path):
    sid = "never-registered"
    transcript = _transcript(tmp_path, sid)
    result = _hook(client, "Stop", sid, transcript)
    assert result["outcome"] == "completed"
    assert any(
        "session_prompt_attestation" in marker
        and "SessionPromptStampRefused" in marker
        for marker in result["degraded"]
    ), result["degraded"]
    assert _row(sid) is None
    assert _refusals(sid) == ["SESSION_PROMPT_STAMP_REFUSED"]


def test_malformed_instant_refuses_without_stamping(client, tmp_path):
    sid = "malformed-instant"
    transcript = _transcript(tmp_path, sid)
    _hook(client, "SessionStart", sid, transcript)
    bad = client_fact(FIRST_USER_PROMPT_KEY, {"session_id": sid, "at": "yesterday"})
    result = _hook(client, "Stop", sid, transcript, extra=bad)
    assert any("SessionPromptStampRefused" in m for m in result["degraded"])
    assert _row(sid)["first_user_prompt_at"] is None
    assert _refusals(sid) == ["SESSION_PROMPT_STAMP_REFUSED"]


def _cursor_hook(client, event, sid, transcript, **native):
    return _hook(
        client, event, sid, transcript, executor="cursor",
        native={"container_session_id": sid, **native},
    )


@pytest.mark.parametrize(
    ("role", "duration", "skip_reason"),
    [
        ("user", {"duration_ms": 4261}, None),
        ("assistant", {"duration_ms": 4261}, "no_user_row"),
        ("user", {}, "missing_duration_ms"),
    ],
)
def test_cursor_print_session_end(client, tmp_path, monkeypatch, role, duration, skip_reason):
    sid = str(uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    transcript.write_text(json.dumps({"role": role, "message": {"content": []}}) + "\n")
    _cursor_hook(client, "SessionStart", sid, transcript)
    assert _row(sid)["first_user_prompt_at"] is None

    end = utc_now()
    monkeypatch.setattr("yoke_core.hooks.context.utc_now", lambda: end)
    _cursor_hook(client, "SessionEnd", sid, transcript, **duration)

    row = _row(sid)
    assert row["ended_at"] is not None
    assert row["tool_call_count"] == 0
    conn = db_helpers.connect()
    try:
        diagnostics = conn.execute(
            "SELECT envelope FROM events WHERE event_name = %s AND session_id = %s",
            ("SessionPromptAttestationSkipped", sid),
        ).fetchall()
    finally:
        conn.close()
    if skip_reason is None:
        assert parse_instant(row["first_user_prompt_at"]) == end - timedelta(milliseconds=4261)
        assert row["probe"] is False
        assert diagnostics == []
    else:
        assert row["first_user_prompt_at"] is None
        assert row["probe"] is True
        event = diagnostics[0]["envelope"]
        event = json.loads(event) if isinstance(event, str) else event
        assert event["context"]["reason"] == skip_reason


def test_cursor_print_tool_completion_is_counted(client, tmp_path):
    sid = str(uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    _cursor_hook(client, "SessionStart", sid, transcript)
    completion = {
        "hook_event_name": "postToolUse",
        "tool_name": "Shell",
        "tool_use_id": str(uuid4()),
        "tool_input": {"command": "echo probe"},
    }
    _cursor_hook(client, "PostToolUse", sid, transcript, **completion)
    _cursor_hook(client, "PostToolUse", sid, transcript, **completion)
    assert _row(sid)["tool_call_count"] == 1
