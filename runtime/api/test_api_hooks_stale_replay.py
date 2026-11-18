"""A hook observed before a session ended cannot revive it when it lands late.

Stage QA for YOK-5351: a resident-timed-out UserPromptSubmit (Claude) or
SessionStart (Codex) finished about 90s later, after SessionEnd, and
revived the ended row — dead sessions showed as working and a probe
reappeared on the roster.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.api_hooks_evaluate_route_test_support import _request_body
from yoke_contracts.hook_evaluator_protocol import (
    EVALUATOR_PAYLOAD_KEY,
    HookEvaluatorRequest,
)
from yoke_contracts.hook_observation_age import (
    HOOK_AGE_FIELD,
    hook_age_ms,
    stamp_hook_age,
)
from yoke_core.domain import db_helpers
from yoke_core.hooks.registration import ensure_registered_from_hook


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _row(sid):
    conn = db_helpers.connect()
    try:
        return conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id = %s", (sid,)
        ).fetchone()
    finally:
        conn.close()


def _end(sid):
    conn = db_helpers.connect()
    try:
        conn.execute(
            "UPDATE harness_sessions SET ended_at = now() WHERE session_id = %s", (sid,)
        )
        conn.commit()
    finally:
        conn.close()


def _hook(client, executor, event, sid, *, age_ms=None):
    payload = {
        "session_id": sid,
        "cwd": "/client/repo",
        "project_id": 1,
        "transcript_path": "/client/saved.jsonl",
        "prompt": "Reply ok",
    }
    if age_ms is not None:
        payload[EVALUATOR_PAYLOAD_KEY] = {HOOK_AGE_FIELD: age_ms}
    body = _request_body(executor=executor, stdin=json.dumps(payload))
    body["event_name"] = event
    response = client.post("/v1/hooks/evaluate", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["exit_code"] == 0
    return result


@pytest.mark.parametrize(
    "executor,late_event",
    [("claude-code", "UserPromptSubmit"), ("codex", "SessionStart"),
     ("cursor", "UserPromptSubmit")],
)
def test_late_finish_of_timed_out_hook_keeps_session_ended(client, executor, late_event):
    sid = f"stale-{executor}"
    _hook(client, executor, "SessionStart", sid, age_ms=0)
    _end(sid)
    ended = _row(sid)["ended_at"]
    # Observed 90s ago, before the end, delivered only now.
    late = _hook(client, executor, late_event, sid, age_ms=90_000)
    assert late["registration_outcome"] == "skipped:stale_replay"
    assert _row(sid)["ended_at"] == ended
    # A hook observed after the end is new activity and still revives.
    time.sleep(0.01)
    fresh = _hook(client, executor, late_event, sid, age_ms=0)
    assert fresh["registration_outcome"] in {"registered", "exists"}
    assert _row(sid)["ended_at"] is None


def test_stale_start_cannot_turn_an_ended_probe_into_a_conversation(client):
    sid = "stale-probe"
    _hook(client, "claude-code", "SessionStart", sid, age_ms=0)
    _end(sid)
    result = _hook(client, "claude-code", "UserPromptSubmit", sid, age_ms=60_000)
    assert result["registration_outcome"] == "skipped:stale_replay"
    row = _row(sid)
    assert row["ended_at"] is not None
    assert row["first_user_prompt_at"] is None


def test_unstamped_hook_from_older_client_keeps_revival(client):
    sid = "unstamped-revival"
    _hook(client, "codex", "SessionStart", sid, age_ms=0)
    _end(sid)
    result = _hook(client, "codex", "SessionStart", sid)
    assert result["registration_outcome"] in {"registered", "exists"}
    assert _row(sid)["ended_at"] is None


def test_batch_instant_before_end_is_stale(client):
    sid = "stale-batch"
    _hook(client, "claude-code", "SessionStart", sid, age_ms=0)
    _end(sid)
    ended = _row(sid)["ended_at"]
    conn = db_helpers.connect()
    try:
        outcome = ensure_registered_from_hook(
            conn,
            json.dumps({"session_id": sid, "project_id": 1}),
            sid,
            register_in_process=True,
            project_id=1,
            observed_at=ended - timedelta(seconds=5),
        )
    finally:
        conn.close()
    assert outcome == "skipped:stale_replay"
    assert _row(sid)["ended_at"] == ended


def test_age_stamp_and_request_round_trip():
    started = time.monotonic() - 2.5
    stamped = stamp_hook_age(json.dumps({"session_id": "s"}), started)
    assert 2400 <= hook_age_ms(stamped) <= 60_000
    assert stamp_hook_age('{"a":1}', None) == '{"a":1}'
    assert hook_age_ms({EVALUATOR_PAYLOAD_KEY: {HOOK_AGE_FIELD: -1}}) is None
    assert hook_age_ms({EVALUATOR_PAYLOAD_KEY: {HOOK_AGE_FIELD: True}}) is None
    request = HookEvaluatorRequest(
        event_name="Stop", stdin="{}", dry_run=False, pid=1, ppid=1, cwd="/",
        environment={}, revision="r", client_started_monotonic=started,
    )
    assert HookEvaluatorRequest.from_mapping(request.to_mapping()) == request
    legacy = request.to_mapping()
    legacy.pop("client_started_monotonic")
    assert HookEvaluatorRequest.from_mapping(legacy).client_started_monotonic is None
