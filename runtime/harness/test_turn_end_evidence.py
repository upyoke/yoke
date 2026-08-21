"""Bounded turn-end evidence fixtures for Claude, Codex, and Cursor."""

from __future__ import annotations

from yoke_contracts.turn_end_evidence import (
    PAYLOAD_KEY,
    UNAVAILABLE,
    extract_from_jsonl,
    extract_turn_end_evidence,
    from_payload_facts,
    read_transcript_tail,
)


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
