"""Folding a Claude transcript's per-message usage into session totals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.harness_family_identity import CLAUDE_FAMILY
from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    USAGE_PARTIAL,
    USAGE_UNAVAILABLE,
)
from yoke_contracts.session_usage_sources import usage_source
from yoke_harness.usage_attestation import attest_session_usage
from yoke_harness.artifact_watermark import (
    TRUNCATED_ARTIFACT_REASON,
    ArtifactWatermark,
    load_watermark,
    save_watermark,
)
from runtime.harness.session_usage_test_support import (  # noqa: F401
    append_rows,
    claude_row,
    machine_home,
    write_rows,
)


def _read(transcript: Path, session_id: str = "session-1"):
    return attest_session_usage(
        "claude-code",
        {"session_id": session_id, "transcript_path": str(transcript)},
        transcript_path=str(transcript),
    )


def test_claude_usage_lands_in_disjoint_billable_buckets(tmp_path: Path) -> None:
    """Cache reads and both cache-write lifetimes stay out of plain input."""
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])

    usage = _read(transcript)

    assert usage.status == USAGE_COMPLETE
    entry = usage.models[0]
    assert entry.model == "claude-opus-5"
    assert entry.input == 10
    assert entry.cached_input == 1_000
    assert entry.cache_write == 200
    assert entry.cache_write_long == 300
    assert entry.output == 100
    assert entry.reasoning == 40
    assert usage.source == usage_source(CLAUDE_FAMILY)
    assert usage.source


def test_reasoning_is_a_subset_of_output_and_not_added_to_the_total(
    tmp_path: Path,
) -> None:
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])

    usage = _read(transcript)

    assert usage.billable_tokens() == 10 + 1_000 + 200 + 300 + 100


def test_content_blocks_sharing_a_message_id_are_counted_once(
    tmp_path: Path,
) -> None:
    """Claude repeats one turn's usage on every content-block row of it."""
    row = claude_row("msg_a")
    transcript = write_rows(tmp_path / "s.jsonl", [row, dict(row), dict(row)])

    usage = _read(transcript)

    assert usage.models[0].output == 100


@pytest.mark.parametrize("incremental", [False, True])
def test_nonconsecutive_repeated_messages_are_counted_once(
    tmp_path: Path, incremental: bool
) -> None:
    rows = [claude_row("msg_a"), claude_row("msg_b")]
    transcript = write_rows(tmp_path / "s.jsonl", rows)
    if incremental:
        _read(transcript)
    # Compaction/resume copies earlier history after newer messages.
    append_rows(transcript, rows + [claude_row("msg_c"), rows[0]])

    usage = _read(transcript)

    assert usage.models[0].output == 300
    assert load_watermark("session-1", transcript).totals["message_ids"] == [
        "msg_a",
        "msg_b",
        "msg_c",
    ]


def test_complete_older_reader_totals_replay_once(tmp_path: Path, monkeypatch) -> None:
    from yoke_harness import usage_attestation

    transcript = write_rows(
        tmp_path / "s.jsonl",
        [claude_row("msg_a"), claude_row("msg_b"), claude_row("msg_a")],
    )
    save_watermark(
        "session-1",
        transcript,
        ArtifactWatermark(
            offset=transcript.stat().st_size,
            last_key="msg_a",
            totals={
                "claude_reader": "projected-v1",
                "models": {"claude-opus-5": {"output": 300}},
            },
        ),
    )
    corrected = _read(transcript)
    assert corrected.models[0].output == 200
    mark = load_watermark("session-1", transcript)
    assert mark.caught_up

    original_scan = usage_attestation.scan_rows
    offsets = []

    def scan(path, offset, *args, **kwargs):
        offsets.append(offset)
        return original_scan(path, offset, *args, **kwargs)

    monkeypatch.setattr(usage_attestation, "scan_rows", scan)
    assert _read(transcript).models[0].output == 200
    assert offsets == [transcript.stat().st_size]


def test_interrupted_reader_replay_does_not_double_apply(
    tmp_path: Path, monkeypatch
) -> None:
    from yoke_harness import usage_attestation

    transcript = write_rows(
        tmp_path / "s.jsonl", [claude_row("msg_a"), claude_row("msg_b")]
    )
    stale = ArtifactWatermark(
        offset=transcript.stat().st_size,
        totals={
            "claude_reader": "projected-v1",
            "models": {"claude-opus-5": {"output": 400}},
        },
    )
    save_watermark("session-1", transcript, stale)
    with monkeypatch.context() as interrupted:

        def crash(*args, **kwargs):
            raise OSError("interrupted before atomic save")

        interrupted.setattr(usage_attestation, "save_watermark", crash)
        assert _read(transcript).status == USAGE_UNAVAILABLE
    assert load_watermark("session-1", transcript) == stale
    assert _read(transcript).models[0].output == 200
    assert _read(transcript).models[0].output == 200


def test_a_split_cache_creation_block_is_not_counted_twice(
    tmp_path: Path,
) -> None:
    """The flat write total and its per-lifetime split state one number."""
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])

    usage = _read(transcript)

    entry = usage.models[0]
    assert entry.cache_write + entry.cache_write_long == 500


def test_a_source_without_a_lifetime_split_reports_one_cache_write_bucket(
    tmp_path: Path,
) -> None:
    row = claude_row("msg_a")
    row["message"]["usage"].pop("cache_creation")
    row["message"]["usage"]["cache_creation_input_tokens"] = 700
    transcript = write_rows(tmp_path / "s.jsonl", [row])

    usage = _read(transcript)

    assert usage.models[0].cache_write == 700
    assert usage.models[0].cache_write_long == 0


def test_rereading_an_unchanged_transcript_does_not_double_count(
    tmp_path: Path,
) -> None:
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])

    first = _read(transcript)
    second = _read(transcript)

    assert second.billable_tokens() == first.billable_tokens()


def test_a_resumed_read_folds_only_what_the_transcript_gained(
    tmp_path: Path,
) -> None:
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])
    first = _read(transcript)
    append_rows(transcript, [claude_row("msg_b")])

    second = _read(transcript)

    assert second.billable_tokens() == first.billable_tokens() * 2


def test_a_turn_split_across_the_resume_boundary_is_counted_once(
    tmp_path: Path,
) -> None:
    """A repeated block arriving after the watermark is still the same turn."""
    row = claude_row("msg_a")
    transcript = write_rows(tmp_path / "s.jsonl", [row])
    first = _read(transcript)
    append_rows(transcript, [dict(row)])

    second = _read(transcript)

    assert second.billable_tokens() == first.billable_tokens()


def test_a_session_that_switched_models_is_attributed_per_model(
    tmp_path: Path,
) -> None:
    transcript = write_rows(
        tmp_path / "s.jsonl",
        [claude_row("msg_a", "claude-sonnet-5"), claude_row("msg_b", "claude-opus-5")],
    )

    usage = _read(transcript)

    assert {entry.model for entry in usage.models} == {
        "claude-sonnet-5",
        "claude-opus-5",
    }
    assert usage.status == USAGE_COMPLETE


def test_a_truncated_transcript_rereads_and_reports_partial(
    tmp_path: Path,
) -> None:
    transcript = write_rows(
        tmp_path / "s.jsonl", [claude_row("msg_a"), claude_row("msg_b")]
    )
    _read(transcript)
    write_rows(transcript, [claude_row("msg_c")])

    usage = _read(transcript)

    assert usage.status == USAGE_PARTIAL
    assert usage.reason == TRUNCATED_ARTIFACT_REASON
    assert usage.models[0].output == 100


def test_a_partially_written_row_waits_for_its_newline(tmp_path: Path) -> None:
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])
    with transcript.open("a") as handle:
        handle.write(json.dumps(claude_row("msg_b"))[:40])

    usage = _read(transcript)

    assert usage.models[0].output == 100


def test_a_missing_claude_transcript_reports_why_rather_than_zero(
    tmp_path: Path,
) -> None:
    usage = attest_session_usage(
        "claude-code",
        {"session_id": "s", "transcript_path": str(tmp_path / "absent.jsonl")},
    )

    assert usage.status == USAGE_UNAVAILABLE
    assert usage.reason
    assert usage.billable_tokens() == 0
    assert usage.source == usage_source(CLAUDE_FAMILY)
    assert usage.source


def test_a_transcript_with_no_assistant_rows_yet_reports_unavailable(
    tmp_path: Path,
) -> None:
    transcript = write_rows(tmp_path / "s.jsonl", [{"type": "user"}])

    usage = _read(transcript)

    assert usage.status == USAGE_UNAVAILABLE
