"""The model a Cursor conversation executed is read from Cursor's own store."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from yoke_harness.cursor_executed_model import (
    executed_model,
    executed_model_for_payload,
)
from yoke_harness.hooks import identity_runtime


CONVERSATION = "148c6d42-ee52-4779-a6e1-7311d842fd14"


def _store(chats: Path, conversation: str, blobs: list[bytes]) -> Path:
    directory = chats / "4aee500d57a39d5ba56a8b6ea85f5ea7" / conversation
    directory.mkdir(parents=True, exist_ok=True)
    store = directory / "store.db"
    connection = sqlite3.connect(store)
    connection.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)")
    for index, blob in enumerate(blobs):
        connection.execute(
            "INSERT INTO blobs (id, data) VALUES (?, ?)", (str(index), blob)
        )
    connection.commit()
    connection.close()
    return store


def _request(model: str) -> bytes:
    return (
        b'{"role":"user","providerOptions":{"cursor":{"modelName":"'
        + model.encode()
        + b'"}},"content":"x"}'
    )


def test_reads_the_variant_the_conversation_last_ran(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    _store(
        chats,
        CONVERSATION,
        [_request("cursor-grok-4.6-high-fast"), _request("cursor-grok-4.6-xhigh")],
    )

    assert executed_model(CONVERSATION, chats_dir=chats) == "cursor-grok-4.6-xhigh"


def test_transcript_text_naming_the_format_is_not_the_model(tmp_path: Path) -> None:
    # An agent quoting this very wire shape into the conversation must not be
    # mistaken for the conversation's own model — it happened while this was
    # being investigated.
    chats = tmp_path / "chats"
    _store(
        chats,
        CONVERSATION,
        [
            _request("cursor-grok-4.6-high-fast"),
            b'{"role":"assistant","content":"grep for '
            b'\\"modelName\\":\\"cursor-grok-4.6-xhigh\\" in the store"}',
        ],
    )

    assert executed_model(CONVERSATION, chats_dir=chats) == "cursor-grok-4.6-high-fast"


def test_a_conversation_with_no_request_yet_reports_nothing(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    _store(chats, CONVERSATION, [b'{"role":"system","content":"boot"}'])

    assert executed_model(CONVERSATION, chats_dir=chats) == ""


def test_an_unknown_or_unsafe_conversation_reports_nothing(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    _store(chats, CONVERSATION, [_request("cursor-grok-4.6-xhigh")])

    assert executed_model("no-such-conversation", chats_dir=chats) == ""
    assert executed_model("../../etc", chats_dir=chats) == ""
    assert executed_model("", chats_dir=chats) == ""


def test_a_subagent_payload_resolves_through_its_container(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CURSOR_TRANSCRIPT_PATH", raising=False)
    chats = tmp_path / "chats"
    _store(chats, CONVERSATION, [_request("cursor-grok-4.6-xhigh")])
    payload = {
        "session_id": "child-conversation",
        "conversation_id": "child-conversation",
        "transcript_path": (
            f"/x/agent-transcripts/{CONVERSATION}/subagents/child.jsonl"
        ),
    }

    assert executed_model_for_payload(payload, chats_dir=chats) == (
        "cursor-grok-4.6-xhigh"
    )


def test_the_measured_model_outranks_what_the_payload_reports(
    monkeypatch, tmp_path: Path
) -> None:
    chats = tmp_path / "chats"
    _store(chats, CONVERSATION, [_request("cursor-grok-4.6-high-fast")])
    monkeypatch.setattr("yoke_harness.cursor_executed_model.CURSOR_CHATS_DIR", chats)

    # The payload's tiered self-report is a claim; the store is the record.
    assert (
        identity_runtime.cursor_payload_model(
            {
                "session_id": CONVERSATION,
                "model": "cursor-grok-4.6-xhigh",
                "model_id": "grok-4.6",
            }
        )
        == "cursor-grok-4.6-high-fast"
    )


def test_the_payload_is_not_the_model_when_the_store_cannot_answer(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "yoke_harness.cursor_executed_model.CURSOR_CHATS_DIR", tmp_path / "empty"
    )

    assert (
        identity_runtime.cursor_payload_model(
            {"session_id": CONVERSATION, "model_id": "grok-4.6"}
        )
        == ""
    )
    assert identity_runtime.cursor_payload_model({"session_id": CONVERSATION}) == ""
