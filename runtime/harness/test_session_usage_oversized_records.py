"""A record too large to hold must not cost a session its accounting.

Two failures motivated every case here, and they are opposites. One
transcript's single oversized row was a user message — it stated no
consumption at all, yet the whole session's usage was marked partial
because something large had been skipped. One rollout's oversized rows
were compacted turns larger than the entire scan budget, so the fold
abandoned them mid-record, advanced inside one, and marked the session's
model history permanently incomplete while its exact cumulative totals
sat unread a few bytes further on.

So these tests hold three things apart: an irrelevant giant record costs
nothing, a relevant giant record is still read, and a relevant record
that genuinely cannot be read is still reported as a gap.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    USAGE_PARTIAL,
)
from yoke_contracts.session_usage_sources import UNNAMED_MODEL
from yoke_harness import artifact_scan
from yoke_harness.artifact_watermark import (
    ArtifactWatermark,
    load_watermark,
    save_watermark,
)
from yoke_harness.codex_artifact_reader import MODEL_HISTORY_INCOMPLETE_KEY
from yoke_harness.codex_usage_attestation import (
    MODEL_HISTORY_GAP_REASON,
)
from yoke_harness.usage_attestation import attest_session_usage
from runtime.harness.session_usage_test_support import (  # noqa: F401
    append_rows,
    claude_row,
    codex_token_count,
    codex_turn_context,
    machine_home,
    write_rows,
)


#: Small enough to keep fixtures fast, large enough that a record can sit
#: on either side of it. The real bound is a megabyte.
SMALL_RECORD_LIMIT = 2_000


def _read_claude(transcript: Path, session_id: str = "session-1"):
    return attest_session_usage(
        "claude-code",
        {"session_id": session_id, "transcript_path": str(transcript)},
        transcript_path=str(transcript),
    )


def _read_codex(
    rollout: Path, monkeypatch: pytest.MonkeyPatch, session_id: str = "codex-1"
):
    from yoke_harness.hooks import identity_codex_runtime

    monkeypatch.setattr(
        identity_codex_runtime,
        "codex_transcript_candidates",
        lambda thread_id, **kwargs: [rollout],
    )
    return attest_session_usage(
        "codex", {"session_id": session_id, "thread_id": "thread-1"}
    )


def _oversized_user_row(size: int) -> dict:
    return {"type": "user", "message": {"role": "user", "content": "x" * size}}


def test_an_oversized_user_row_does_not_make_a_session_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It states no consumption, so losing its content loses nothing."""
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", SMALL_RECORD_LIMIT)
    transcript = write_rows(
        tmp_path / "s.jsonl",
        [
            claude_row("msg_a"),
            _oversized_user_row(SMALL_RECORD_LIMIT * 3),
            claude_row("msg_b"),
        ],
    )

    usage = _read_claude(transcript)

    assert usage.status == USAGE_COMPLETE
    assert not usage.reason
    assert usage.models[0].output == 200


def test_an_oversized_assistant_row_still_states_its_own_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counts are small however much content sits beside them."""
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", SMALL_RECORD_LIMIT)
    row = claude_row("msg_a")
    row["padding"] = "x" * (SMALL_RECORD_LIMIT * 3)
    transcript = write_rows(tmp_path / "s.jsonl", [row])

    usage = _read_claude(transcript)

    assert usage.status == USAGE_COMPLETE
    assert usage.models[0].model == "claude-opus-5"
    assert usage.models[0].output == 100
    assert usage.models[0].cached_input == 1_000


def test_an_unreadable_assistant_row_is_still_reported_as_a_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Honest partiality survives: a lost usage statement is still lost."""
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", SMALL_RECORD_LIMIT)
    broken = claude_row("msg_a")
    broken["message"]["usage"] = {"input_tokens": "x" * (SMALL_RECORD_LIMIT * 3)}
    transcript = write_rows(tmp_path / "s.jsonl", [broken, claude_row("msg_b")])

    usage = _read_claude(transcript)

    assert usage.status == USAGE_PARTIAL
    assert usage.reason
    assert usage.models[0].output == 100


def test_a_claude_record_written_by_the_previous_reader_is_folded_again(
    tmp_path: Path,
) -> None:
    """Replaying an additive fold must not count its rows a second time."""
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])
    expected = _read_claude(transcript, session_id="stale-1").billable_tokens()
    stale = load_watermark("stale-1", transcript)
    save_watermark(
        "stale-1",
        transcript,
        ArtifactWatermark(
            offset=stale.offset,
            last_key=stale.last_key,
            totals={"models": stale.totals["models"]},
            oversized=True,
        ),
    )

    usage = _read_claude(transcript, session_id="stale-1")

    assert usage.billable_tokens() == expected
    assert usage.status == USAGE_COMPLETE
    assert load_watermark("stale-1", transcript).offset == transcript.stat().st_size


def test_a_codex_record_wider_than_one_scan_still_yields_its_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compacted record is passed over; the total after it is read."""
    monkeypatch.setattr(artifact_scan, "MAX_SCAN_BYTES", 4_000)
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", SMALL_RECORD_LIMIT)
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("gpt-5.1-codex-max"),
            {
                "type": "response_item",
                "payload": {"type": "message", "text": "x" * 40_000},
            },
            codex_token_count(input_tokens=900, cached=400, output=70),
        ],
    )

    usage = _read_codex(rollout, monkeypatch)
    while not usage.models:
        usage = _read_codex(rollout, monkeypatch)

    assert usage.status == USAGE_COMPLETE
    assert not usage.cost_caveat
    assert usage.models[0].input == 500
    assert usage.models[0].output == 70


def test_a_codex_model_gap_leaves_the_tokens_exact_and_the_price_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", SMALL_RECORD_LIMIT)
    unreadable = codex_turn_context("gpt-5.1-codex-max")
    unreadable["payload"]["model"] = "x" * (SMALL_RECORD_LIMIT * 3)
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [unreadable, codex_token_count(input_tokens=500, output=50)],
    )

    usage = _read_codex(rollout, monkeypatch)

    assert usage.status == USAGE_COMPLETE
    assert usage.cost_caveat == MODEL_HISTORY_GAP_REASON
    assert usage.billable_tokens() == 550
    assert usage.models[0].model == UNNAMED_MODEL


def test_a_codex_record_written_by_the_previous_reader_clears_its_stale_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gap the current reader would not hit must not outlive that reader."""
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("gpt-5.1-codex-max"),
            codex_token_count(input_tokens=500, output=50),
        ],
    )
    _read_codex(rollout, monkeypatch, session_id="stale-codex")
    stale = load_watermark("stale-codex", rollout)
    totals = dict(stale.totals)
    totals[MODEL_HISTORY_INCOMPLETE_KEY] = True
    totals["codex_reader"] = "projected-v1"
    save_watermark(
        "stale-codex",
        rollout,
        ArtifactWatermark(
            offset=stale.offset,
            last_key=stale.last_key,
            totals=totals,
            oversized=True,
        ),
    )

    usage = _read_codex(rollout, monkeypatch, session_id="stale-codex")

    assert usage.status == USAGE_COMPLETE
    assert not usage.cost_caveat
    assert usage.billable_tokens() == 550


def test_a_transcript_holding_a_fourteen_megabyte_record_reads_promptly(
    tmp_path: Path,
) -> None:
    """The shape that stalled a real session, at its real size.

    A hook event pays for this read, so the cost that matters is wall
    clock: the record is streamed past rather than examined byte by byte,
    which is what keeps a session's own tooling from stalling on it.
    """
    transcript = write_rows(
        tmp_path / "s.jsonl",
        [
            claude_row("msg_a"),
            _oversized_user_row(14 * 1024 * 1024),
            claude_row("msg_b"),
        ],
    )

    started = time.monotonic()
    usage = _read_claude(transcript)
    elapsed = time.monotonic() - started

    assert usage.status == USAGE_COMPLETE
    assert usage.models[0].output == 200
    assert elapsed < 10
