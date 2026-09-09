"""A fold that has not reached the end says so rather than reading as whole.

Each artifact here is deliberately larger than the bound the fold is
given, which is the shape a session hits when its transcript grows faster
than the events folding it: the accounting is real but partial, and the
harm is presenting it as the whole session's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_harness import artifact_scan
from yoke_harness.artifact_watermark import (
    MODEL_KIND,
    load_watermark,
    partial_reason,
    watermark_lock,
)
from yoke_harness.model_attestation import _codex_rollout_facts
from yoke_harness.usage_attestation import attest_session_usage
from runtime.harness.session_usage_test_support import (  # noqa: F401
    claude_row,
    codex_turn_context,
    machine_home,
    write_rows,
)


def _read_claude(transcript: Path, session_id: str = "session-1"):
    return attest_session_usage(
        "claude-code",
        {"session_id": session_id, "transcript_path": str(transcript)},
        transcript_path=str(transcript),
    )


def test_a_reading_that_stopped_short_of_the_artifact_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = write_rows(
        tmp_path / "s.jsonl", [claude_row(f"msg_{index}") for index in range(6)]
    )

    with monkeypatch.context() as bounded:
        bounded.setattr(artifact_scan, "MAX_SCAN_BYTES", 400)
        usage = _read_claude(transcript)

    assert usage.status == "partial"
    assert usage.reason == artifact_scan.CATCH_UP_PENDING_REASON


def test_a_contender_reading_a_record_left_behind_says_it_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cached totals from a fold that stopped short are not complete."""
    transcript = write_rows(
        tmp_path / "s.jsonl", [claude_row(f"msg_{index}") for index in range(6)]
    )
    with monkeypatch.context() as bounded:
        bounded.setattr(artifact_scan, "MAX_SCAN_BYTES", 400)
        _read_claude(transcript)

    with watermark_lock("session-1"):
        contender = _read_claude(transcript)

    assert contender.status == "partial"
    assert contender.reason == artifact_scan.CATCH_UP_PENDING_REASON


def test_catching_up_clears_the_partial_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = write_rows(
        tmp_path / "s.jsonl", [claude_row(f"msg_{index}") for index in range(6)]
    )
    with monkeypatch.context() as bounded:
        bounded.setattr(artifact_scan, "MAX_SCAN_BYTES", 400)
        _read_claude(transcript)

    usage = _read_claude(transcript)

    assert usage.status == "complete"
    assert usage.billable_tokens() == 6 * (10 + 1_000 + 200 + 300 + 100)


def test_model_facts_are_not_attested_from_a_fold_that_stopped_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A settled session reports its model for life, so a stale one cannot land."""
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [codex_turn_context("gpt-5")]
        + [{"type": "event_msg", "payload": {"filler": "a" * 2_000}}] * 4
        + [codex_turn_context("gpt-5-codex")],
    )

    with monkeypatch.context() as bounded:
        bounded.setattr(artifact_scan, "MAX_SCAN_BYTES", 600)
        behind = _codex_rollout_facts(rollout, "thread-1")

    assert not behind.attested()
    assert _codex_rollout_facts(rollout, "thread-1").model == "gpt-5-codex"


def test_a_contending_model_reader_of_a_record_left_behind_attests_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [codex_turn_context("gpt-5")]
        + [{"type": "event_msg", "payload": {"filler": "a" * 2_000}}] * 4,
    )
    with monkeypatch.context() as bounded:
        bounded.setattr(artifact_scan, "MAX_SCAN_BYTES", 600)
        _codex_rollout_facts(rollout, "thread-1")

    with watermark_lock("thread-1", kind=MODEL_KIND):
        contender = _codex_rollout_facts(rollout, "thread-1")

    assert not contender.attested()


def test_a_skipped_oversized_record_keeps_saying_the_total_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = claude_row("msg_a")
    row["message"]["filler"] = "x" * 1_000
    transcript = write_rows(tmp_path / "s.jsonl", [row, claude_row("msg_b")])

    with monkeypatch.context() as bounded:
        bounded.setattr(artifact_scan, "MAX_RECORD_BYTES", 800)
        usage = _read_claude(transcript)

    assert usage.status == "partial"
    assert usage.reason == artifact_scan.OVERSIZED_RECORD_REASON
    assert usage.models[0].output == 100
    assert partial_reason(load_watermark("session-1", transcript)) == (
        artifact_scan.OVERSIZED_RECORD_REASON
    )


def test_a_large_unrelated_record_does_not_disturb_the_totals(
    tmp_path: Path,
) -> None:
    transcript = write_rows(
        tmp_path / "s.jsonl",
        [{"type": "user", "filler": "u" * 400_000}, claude_row("msg_a")],
    )

    usage = _read_claude(transcript)

    assert usage.models[0].output == 100
