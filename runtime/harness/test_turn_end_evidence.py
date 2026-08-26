"""Bounded turn-end evidence fixtures for Claude, Codex, and Cursor."""

from __future__ import annotations

import json

from yoke_contracts.turn_end_evidence import (
    PAYLOAD_KEY,
    REPORT_PAYLOAD_KEY,
    TurnEndReport,
    UNAVAILABLE,
    extract_from_jsonl,
    extract_report_from_jsonl,
    extract_turn_end_evidence,
    extract_turn_end_report,
    from_payload_facts,
    read_transcript_tail,
)
from yoke_harness.hooks.deadline import start_hook_deadline
from yoke_harness.hooks.local_subset import evaluate_local_subset


def test_payload_facts_win_over_transcript() -> None:
    evidence = extract_turn_end_evidence(
        payload={PAYLOAD_KEY: {"available": True, "present": True, "question": True}},
        transcript_text='{"role":"assistant","content":"Keep going."}\n',
    )
    assert evidence.available is True
    assert evidence.question is True


def test_final_response_field_normalizes() -> None:
    evidence = from_payload_facts({"final_response": "Ready to continue?"})
    assert evidence is not None
    assert evidence.present is True
    assert evidence.question is True


def test_projected_report_wins_over_transcript() -> None:
    report = extract_turn_end_report(
        payload={
            REPORT_PAYLOAD_KEY: {
                "body": "Projected report.",
                "fingerprint": "turn-1",
            }
        },
        transcript_text='{"role":"assistant","content":"Ignored."}\n',
    )
    assert report == TurnEndReport(body="Projected report.", fingerprint="turn-1")


def test_question_on_earlier_line_is_detected() -> None:
    evidence = from_payload_facts(
        {"final_response": "Should I continue?\nI will wait for your answer."}
    )
    assert evidence is not None
    assert evidence.question is True


def test_missing_evidence_is_unavailable() -> None:
    assert extract_turn_end_evidence(payload={}) is UNAVAILABLE


def test_malformed_jsonl_is_unavailable() -> None:
    assert extract_from_jsonl("{not-json\n").available is False


def test_claude_assistant_text_is_present() -> None:
    text = (
        '{"type":"user","message":{"role":"user","content":"go"}}\n'
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"text","text":"I will implement this next."}]}}\n'
    )
    evidence = extract_from_jsonl(text)
    assert evidence.available is True
    assert evidence.present is True
    assert evidence.question is False


def test_claude_question_is_detected() -> None:
    text = (
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"text","text":"Should I continue?"}]}}\n'
    )
    assert extract_from_jsonl(text).question is True


def test_claude_question_before_closing_line_is_detected() -> None:
    text = (
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"text","text":"Should I continue?\\nStopping here."}]}}\n'
    )
    assert extract_from_jsonl(text).question is True


def test_codex_agent_message_is_present() -> None:
    text = (
        '{"type":"event_msg","payload":{"type":"agent_message",'
        '"message":"Continuing the implementation."}}\n'
    )
    evidence = extract_from_jsonl(text)
    assert evidence.available is True
    assert evidence.question is False


def test_codex_output_text_is_present() -> None:
    text = (
        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
        '"content":[{"type":"output_text","text":"Done for now?"}]}}\n'
    )
    assert extract_from_jsonl(text).question is True


def test_jsonl_report_uses_last_main_agent_record() -> None:
    text = (
        '{"role":"assistant","content":"Earlier."}\n'
        '{"role":"assistant","parent_conversation_id":"parent",'
        '"content":"Subagent."}\n'
        '{"role":"assistant","content":"Final report."}\n'
    )
    first = extract_report_from_jsonl(text)
    second = extract_report_from_jsonl(text)
    assert first is not None
    assert first.body == "Final report."
    assert first.fingerprint == second.fingerprint


def test_cursor_assistant_text_is_present() -> None:
    text = (
        '{"role":"assistant","message":{"content":'
        '[{"type":"text","text":"Holding the claim and proceeding."}]}}\n'
    )
    evidence = extract_from_jsonl(text)
    assert evidence.available is True
    assert evidence.present is True


def test_user_and_subagent_lines_are_ignored() -> None:
    text = (
        '{"role":"user","message":{"content":[{"type":"text","text":"Stop?"}]}}\n'
        '{"role":"assistant","parent_conversation_id":"parent",'
        '"message":{"content":[{"type":"text","text":"Subagent done?"}]}}\n'
        '{"role":"assistant","message":{"content":'
        '[{"type":"text","text":"Main agent will continue."}]}}\n'
    )
    evidence = extract_from_jsonl(text)
    assert evidence.question is False
    assert evidence.present is True


def test_tool_only_assistant_line_is_not_final_text() -> None:
    text = (
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"tool_use","name":"Bash","input":{}}]}}\n'
    )
    assert extract_from_jsonl(text).available is False


def test_read_transcript_tail_returns_none_for_missing_path(tmp_path) -> None:
    assert read_transcript_tail(str(tmp_path / "missing.jsonl")) is None


def test_claude_and_codex_relay_project_the_same_turn_report(tmp_path) -> None:
    transcript = tmp_path / "turn.jsonl"
    transcript.write_text(
        '{"role":"assistant","content":"Route this report."}\n',
        encoding="utf-8",
    )
    stdin_data = json.dumps(
        {"session_id": "session-1", "transcript_path": str(transcript)}
    )

    for executor in ("claude-code", "codex"):
        local = evaluate_local_subset(
            "Stop",
            stdin_data,
            executor,
            None,
            start_hook_deadline(),
        )
        assert local.payload_extra is not None
        assert local.payload_extra[REPORT_PAYLOAD_KEY]["body"] == ("Route this report.")
