"""Per-harness read-back of what a provider actually served."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from yoke_harness.model_attestation import attest_served_facts


def _claude_transcript(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def _assistant(model: str, effort: str | None = None) -> dict:
    row: dict = {"type": "assistant", "message": {"model": model}}
    if effort is not None:
        row["effort"] = effort
    return row


def test_claude_reports_the_served_model_and_effort_from_its_transcript(
    tmp_path: Path,
) -> None:
    transcript = _claude_transcript(
        tmp_path / "session.jsonl",
        [_assistant("claude-sonnet-5", "low"), _assistant("claude-opus-5", "high")],
    )

    facts = attest_served_facts(
        "claude-code", {}, transcript_path=str(transcript)
    )

    assert facts.model == "claude-opus-5"
    assert facts.reasoning_effort == "high"


def test_claude_declares_no_context_window(tmp_path: Path) -> None:
    """The tier is only measurable from consumption, never declared."""
    transcript = _claude_transcript(
        tmp_path / "session.jsonl", [_assistant("claude-opus-5", "high")]
    )

    facts = attest_served_facts("claude-code", {}, transcript_path=str(transcript))

    assert facts.context_window_tokens is None


def test_an_unreadable_claude_transcript_attests_nothing(tmp_path: Path) -> None:
    facts = attest_served_facts(
        "claude-code", {}, transcript_path=str(tmp_path / "absent.jsonl")
    )

    assert not facts.attested()


def test_a_transcript_naming_only_placeholders_attests_nothing(
    tmp_path: Path,
) -> None:
    transcript = _claude_transcript(
        tmp_path / "session.jsonl", [_assistant("<synthetic>"), _assistant("default")]
    )

    facts = attest_served_facts("claude-code", {}, transcript_path=str(transcript))

    assert facts.model is None


def _codex_rollout(root: Path, thread_id: str, rows: list[dict]) -> Path:
    directory = root / "2026" / "08" / "31"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-2026-08-31T12-09-33-{thread_id}.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def test_codex_reports_model_effort_and_its_declared_window(
    monkeypatch, tmp_path: Path
) -> None:
    thread = "01a05895-484b-7ab2-b3b2-5b88a84df583"
    root = tmp_path / "sessions"
    _codex_rollout(
        root,
        thread,
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.6-sol", "effort": "low"}},
            {
                "type": "event_msg",
                "payload": {"model_context_window": 258400},
            },
        ],
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_codex_runtime.codex_transcript_roots",
        lambda: [root],
    )

    facts = attest_served_facts("codex", {"thread_id": thread})

    assert facts.model == "gpt-5.6-sol"
    assert facts.reasoning_effort == "low"
    assert facts.context_window_tokens == 258400


def test_codex_reads_the_window_from_a_nested_token_count_row(
    monkeypatch, tmp_path: Path
) -> None:
    thread = "01a05895-484b-7ab2-b3b2-5b88a84df584"
    root = tmp_path / "sessions"
    _codex_rollout(
        root,
        thread,
        [
            {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
            {
                "type": "event_msg",
                "payload": {"info": {"model_context_window": 400000}},
            },
        ],
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_codex_runtime.codex_transcript_roots",
        lambda: [root],
    )

    facts = attest_served_facts("codex", {"thread_id": thread})

    assert facts.context_window_tokens == 400000


def test_a_codex_session_with_no_rollout_attests_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "yoke_harness.hooks.identity_codex_runtime.codex_transcript_roots",
        lambda: [tmp_path / "empty"],
    )

    facts = attest_served_facts("codex", {"thread_id": "no-such-thread"})

    assert not facts.attested()


def _cursor_store(chats: Path, conversation: str, model: str) -> None:
    directory = chats / "4aee500d57a39d5ba56a8b6ea85f5ea7" / conversation
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "store.db")
    connection.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)")
    connection.execute(
        "INSERT INTO blobs (id, data) VALUES (?, ?)",
        (
            "0",
            b'{"providerOptions":{"cursor":{"modelName":"' + model.encode() + b'"}}}',
        ),
    )
    connection.commit()
    connection.close()


def test_cursor_reports_the_variant_its_store_names(monkeypatch, tmp_path: Path) -> None:
    conversation = "148c6d42-ee52-4779-a6e1-7311d842fd14"
    chats = tmp_path / "chats"
    _cursor_store(chats, conversation, "cursor-grok-4.6-xhigh")
    monkeypatch.setattr("yoke_harness.cursor_executed_model.CURSOR_CHATS_DIR", chats)

    facts = attest_served_facts("cursor", {"session_id": conversation})

    assert facts.model == "cursor-grok-4.6-xhigh"


def test_cursors_variant_name_is_simultaneously_its_served_effort(
    monkeypatch, tmp_path: Path
) -> None:
    conversation = "148c6d42-ee52-4779-a6e1-7311d842fd15"
    chats = tmp_path / "chats"
    _cursor_store(chats, conversation, "cursor-grok-4.6-xhigh")
    monkeypatch.setattr("yoke_harness.cursor_executed_model.CURSOR_CHATS_DIR", chats)

    facts = attest_served_facts("cursor", {"session_id": conversation})

    assert facts.reasoning_effort == "xhigh"


def test_cursor_without_a_store_attests_nothing_rather_than_the_payload(
    monkeypatch, tmp_path: Path
) -> None:
    """The payload's bare family id is a claim, never a measurement."""
    monkeypatch.setattr(
        "yoke_harness.cursor_executed_model.CURSOR_CHATS_DIR", tmp_path / "empty"
    )

    facts = attest_served_facts(
        "cursor",
        {"session_id": "148c6d42-ee52-4779-a6e1-7311d842fd16", "model": "grok-4.6"},
    )

    assert not facts.attested()
