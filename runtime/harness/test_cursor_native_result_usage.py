"""A finished Cursor native's own result reaches session accounting.

The fixture below is one real installed-CLI result line with its ids
replaced: a print-mode turn writes exactly this single JSON object to
stdout as it exits, after the turn's last hook has already run.
"""

from __future__ import annotations

from pathlib import Path
import json
import sqlite3

from yoke_contracts.session_usage_facts import usage_from_document
from yoke_contracts.session_usage_sources import CURSOR_UNNAMED_MODEL
from yoke_harness.cursor_native_result_usage import (
    fold_launch_native_result,
    fold_native_result_usage,
    native_result_payload,
    session_usage_document,
)
from yoke_harness.session_relay_native_capture_format import (
    STATE_EXITED,
    STATE_RUNNING,
    compose_capture,
    parse_capture,
)
from runtime.harness.session_usage_test_support import (  # noqa: F401
    machine_home,
)


CONVERSATION = "fc6a9de6-66d6-4e8a-a740-3f83262475ac"
REQUEST = "77fbd870-80b3-4816-b4f9-f4a6150e9c3c"

#: One real ``cursor-agent --print --output-format json`` result, redacted.
NATIVE_RESULT_LINE = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 17137,
        "duration_api_ms": 17137,
        "result": "ok",
        "session_id": CONVERSATION,
        "request_id": REQUEST,
        "usage": {
            "inputTokens": 102596,
            "outputTokens": 30,
            "cacheReadTokens": 9600,
            "cacheWriteTokens": 0,
        },
    }
)


def _capture(stdout: str, *, state: str = STATE_EXITED, exit_code: int | None = 0):
    return parse_capture(
        compose_capture(
            stdout=stdout.encode(),
            stderr=b"",
            state=state,
            exit_code=exit_code,
        )
    )


def _result_line(*, request_id: str, output_tokens: int = 30) -> str:
    payload = json.loads(NATIVE_RESULT_LINE)
    payload["request_id"] = request_id
    payload["usage"]["outputTokens"] = output_tokens
    return json.dumps(payload)


def _store_naming(chats: Path, model: str) -> None:
    directory = chats / "4aee500d57a39d5ba56a8b6ea85f5ea7" / CONVERSATION
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


def test_settled_result_folds_the_turn_the_hooks_could_not_see() -> None:
    document = fold_native_result_usage(_capture(NATIVE_RESULT_LINE))

    usage = usage_from_document(document)
    assert usage is not None and usage.measured()
    entry = usage.models[0]
    assert entry.input == 102596
    assert entry.cached_input == 9600
    assert entry.cache_write == 0
    assert entry.output == 30
    assert session_usage_document(CONVERSATION) == document


def test_a_redelivered_result_is_counted_once() -> None:
    first = fold_native_result_usage(_capture(NATIVE_RESULT_LINE))
    again = fold_native_result_usage(_capture(NATIVE_RESULT_LINE))

    assert usage_from_document(again).billable_tokens() == (
        usage_from_document(first).billable_tokens()
    )


def test_each_resumed_turn_accumulates_onto_the_session_total() -> None:
    fold_native_result_usage(_capture(_result_line(request_id="turn-one")))
    fold_native_result_usage(
        _capture(_result_line(request_id="turn-two", output_tokens=70))
    )

    usage = usage_from_document(session_usage_document(CONVERSATION))
    assert usage.models[0].output == 100
    assert usage.models[0].input == 102596 * 2


def test_a_result_still_being_written_folds_nothing_yet() -> None:
    partial = NATIVE_RESULT_LINE[: len(NATIVE_RESULT_LINE) // 2]

    assert (
        fold_native_result_usage(_capture(partial, state=STATE_RUNNING, exit_code=None))
        == ""
    )
    assert session_usage_document(CONVERSATION) == ""


def test_a_result_stating_no_usage_folds_nothing() -> None:
    without_usage = json.dumps(
        {"type": "result", "subtype": "success", "session_id": CONVERSATION}
    )

    assert native_result_payload(_capture(without_usage)) is None
    assert fold_native_result_usage(_capture(without_usage)) == ""
    assert session_usage_document(CONVERSATION) == ""


def test_a_capture_with_no_result_at_all_folds_nothing() -> None:
    assert fold_native_result_usage(_capture("thinking...\n")) == ""
    assert fold_native_result_usage(None) == ""


def test_the_conversations_own_store_names_the_served_model(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    _store_naming(chats, "cursor-grok-4.6-high")

    document = fold_native_result_usage(_capture(NATIVE_RESULT_LINE), chats_dir=chats)

    assert usage_from_document(document).models[0].model == "cursor-grok-4.6-high"


def test_a_conversation_naming_no_model_is_not_given_one(tmp_path: Path) -> None:
    document = fold_native_result_usage(
        _capture(NATIVE_RESULT_LINE), chats_dir=tmp_path / "empty"
    )

    assert usage_from_document(document).models[0].model == CURSOR_UNNAMED_MODEL


def test_a_launch_capture_is_folded_by_its_launch_id(tmp_path: Path) -> None:
    from yoke_harness.session_relay_native_diagnostics import (
        diagnostic_reference,
        native_diagnostic_path,
        write_native_capture,
    )

    launch_id = "33333333-3333-4333-8333-333333333333"
    write_native_capture(
        native_diagnostic_path(
            diagnostic_reference(launch_id), state_dir=tmp_path, create=True
        ),
        compose_capture(
            stdout=NATIVE_RESULT_LINE.encode(),
            stderr=b"",
            state=STATE_EXITED,
            exit_code=0,
        ),
    )

    document = fold_launch_native_result(launch_id, state_dir=tmp_path)

    assert usage_from_document(document).billable_tokens() > 0
    assert session_usage_document(CONVERSATION) == document


def test_an_unreadable_launch_reference_folds_nothing(tmp_path: Path) -> None:
    assert fold_launch_native_result("not-a-launch-id", state_dir=tmp_path) == ""
