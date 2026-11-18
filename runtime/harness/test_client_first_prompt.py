"""The client attests a first prompt only from this session's real user rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.hook_runner.client_facts import (
    FIRST_USER_PROMPT_KEY,
    first_user_prompt_at,
    read_client_fact,
)
from yoke_harness.artifact_scan import MAX_RECORD_BYTES
from yoke_harness.hooks import client_facts
from yoke_harness.hooks.client_first_prompt import claude_first_prompt_at

SID = "8889a55c-8e72-4deb-b21f-57f2dd0abfd8"
AT = "2026-11-17T23:20:41.512Z"


def _write(tmp_path: Path, rows) -> Path:
    path = tmp_path / f"{SID}.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def _user(content, **extra):
    return {"type": "user", "sessionId": SID, "timestamp": AT,
            "message": {"role": "user", "content": content}, **extra}


def _facts(event, transcript, executor="claude-code", **native):
    payload = {"session_id": SID, "transcript_path": str(transcript), **native}
    return client_facts.collect_client_facts(
        event, payload, executor, client_facts.event_chain(event, payload)
    )


@pytest.mark.parametrize(
    "noise",
    [
        _user("caveat", isMeta=True),
        _user("child prompt", isSidechain=True),
        _user("summary", isCompactSummary=True),
        _user("<local-command-stdout>ok</local-command-stdout>"),
        _user([{"type": "tool_result", "tool_use_id": "t", "content": "x"}]),
        {**_user("other session"), "sessionId": "another-session"},
        {"type": "assistant", "sessionId": SID, "timestamp": AT,
         "message": {"role": "assistant", "content": "hi"}},
    ],
)
def test_non_prompt_rows_never_attest(tmp_path, noise):
    assert claude_first_prompt_at(_write(tmp_path, [noise]), SID) is None


def test_first_real_prompt_wins_over_later_ones(tmp_path):
    rows = [
        _user("meta", isMeta=True),
        _user([{"type": "text", "text": "Reply ok"}]),
        {**_user("later"), "timestamp": "2026-11-17T23:30:00Z"},
    ]
    assert claude_first_prompt_at(_write(tmp_path, rows), SID) == (
        "2026-11-17T23:20:41.512000Z"
    )


def test_oversized_prompt_and_tool_result_rows_are_classified(tmp_path):
    huge = "x" * (MAX_RECORD_BYTES + 10)
    tool = _user([{"type": "tool_result", "tool_use_id": "t", "content": huge}])
    assert claude_first_prompt_at(_write(tmp_path, [tool]), SID) is None
    assert claude_first_prompt_at(_write(tmp_path, [tool, _user(huge)]), SID) == (
        "2026-11-17T23:20:41.512000Z"
    )


@pytest.mark.parametrize("event", ["Stop", "SessionEnd"])
def test_terminal_chains_carry_the_attestation_without_prompt_text(tmp_path, event):
    transcript = _write(tmp_path, [_user("secret prompt text")])
    facts = _facts(event, transcript)
    assert first_user_prompt_at(facts, SID) == "2026-11-17T23:20:41.512000Z"
    assert "secret prompt text" not in json.dumps(facts[FIRST_USER_PROMPT_KEY])


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit"])
def test_non_terminal_events_do_not_attest(tmp_path, event):
    assert FIRST_USER_PROMPT_KEY not in _facts(event, _write(tmp_path, [_user("hi")]))


@pytest.mark.parametrize("executor", ["codex", "cursor"])
def test_stop_without_native_prompt_timestamps_ships_nothing(tmp_path, executor):
    facts = _facts("Stop", _write(tmp_path, [_user("hi")]), executor)
    assert FIRST_USER_PROMPT_KEY not in facts


def test_missing_transcript_ships_nothing(tmp_path):
    assert FIRST_USER_PROMPT_KEY not in _facts("Stop", tmp_path / "absent.jsonl")


def test_cursor_session_end_ships_duration_without_prompt_content(tmp_path):
    prompt = "x" * (MAX_RECORD_BYTES + 10)
    transcript = _write(tmp_path, [{"role": "user", "message": {"content": prompt}}])
    facts = _facts("SessionEnd", transcript, "cursor", duration_ms=0)
    assert read_client_fact(facts, FIRST_USER_PROMPT_KEY) == {
        "session_id": SID,
        "duration_ms": 0,
    }
