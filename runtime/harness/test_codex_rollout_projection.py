"""Codex rollout reads retain facts, never the payloads surrounding them."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from yoke_contracts.session_usage_cost import COST_PARTIAL, session_cost
from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    USAGE_PARTIAL,
    USAGE_UNAVAILABLE,
)
from yoke_harness import artifact_scan
from yoke_harness.artifact_scan import scan_rows
from yoke_harness.artifact_watermark import (
    ArtifactWatermark,
    load_watermark,
    save_watermark,
)
from yoke_harness.codex_artifact_reader import codex_record_decoder
from yoke_harness.codex_usage_attestation import (
    MODEL_HISTORY_GAP_REASON,
    USAGE_GAP_REASON,
)
from yoke_harness.model_attestation import _codex_rollout_facts
from yoke_harness.usage_attestation import attest_session_usage
from runtime.harness.session_usage_test_support import (  # noqa: F401
    append_rows,
    codex_token_count,
    codex_turn_context,
    machine_home,
    write_rows,
)


def _read_codex(
    rollout: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_id: str = "codex-projection",
):
    from yoke_harness.hooks import identity_codex_runtime

    monkeypatch.setattr(
        identity_codex_runtime,
        "codex_transcript_candidates",
        lambda _thread_id, **_kwargs: [rollout],
    )
    return attest_session_usage(
        "codex", {"session_id": session_id, "thread_id": "thread-projection"}
    )


def _large_token_row(input_tokens: int = 1_000, *, padding: int = 4_000) -> dict:
    row = codex_token_count(
        input_tokens=input_tokens,
        cached=400,
        cache_write=50,
        output=80,
        reasoning=20,
    )
    payload = row["payload"]
    return {
        "irrelevant_before_type": "🙂" * padding,
        "payload": {
            "large_before_type": 'escaped \\"token_count\\" ' * padding,
            "info": payload["info"],
            "type": payload["type"],
            "large_after_usage": "x" * padding,
        },
        "type": row["type"],
    }


def test_ordinary_rows_decode_normally_and_oversized_rows_are_projected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", 300)
    monkeypatch.setattr(artifact_scan, "_READ_CHUNK_BYTES", 7)
    artifact = write_rows(
        tmp_path / "rollout.jsonl",
        [
            {
                "payload": {"message": 'text says \\"type\\":\\"token_count\\"'},
                "type": "event_msg",
            },
            {
                "payload": {"model": "gpt-5-🙂", "effort": "high"},
                "type": "turn_context",
            },
            _large_token_row(),
        ],
    )
    projected: list[dict] = []
    small = write_rows(tmp_path / "small.jsonl", [codex_turn_context("gpt-5")])

    result = scan_rows(
        artifact,
        0,
        projected.append,
        record_factory=codex_record_decoder,
    )
    small_result = scan_rows(
        small, 0, lambda _row: None, record_factory=codex_record_decoder
    )
    assert result.bytes_read == artifact.stat().st_size
    assert result.records_decoded == 2
    assert small_result.records_decoded == 1
    assert result.peak_retained_bytes == artifact_scan.MAX_RECORD_BYTES + 1
    assert small_result.peak_retained_bytes < artifact_scan.MAX_RECORD_BYTES
    assert not result.oversized
    assert projected[1]["payload"]["model"] == "gpt-5-🙂"
    usage = projected[2]["payload"]["info"]["total_token_usage"]
    assert usage["input_tokens"] == 1_000


def test_large_relevant_and_unrelated_rows_preserve_exact_usage_and_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", 300)
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            {"type": "response_item", "payload": {"body": "u" * 20_000}},
            {
                "payload": {"filler": "m" * 10_000, "model": "priced"},
                "type": "turn_context",
            },
            _large_token_row(),
            {"type": "response_item", "payload": {"body": "z" * 20_000}},
        ],
    )

    usage = _read_codex(rollout, monkeypatch)

    assert usage.status == USAGE_COMPLETE
    assert usage.models[0].model == "priced"
    assert usage.models[0].input == 600
    assert usage.models[0].cached_input == 400
    assert usage.models[0].cache_write == 50
    assert usage.models[0].output == 80
    assert usage.models[0].reasoning == 20
    cost = session_cost(usage, lambda _model: _Price())
    assert cost.usd == pytest.approx(0.0013)


def test_misleading_token_text_never_becomes_a_usage_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = json.dumps(codex_token_count(input_tokens=99_999, output=9_999))
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("priced"),
            {"type": "response_item", "payload": {"message": fake}},
            codex_token_count(input_tokens=200, cached=50, output=10),
        ],
    )

    usage = _read_codex(rollout, monkeypatch)

    assert usage.models[0].input == 150
    assert usage.models[0].cached_input == 50
    assert usage.models[0].output == 10


def test_unchanged_reads_do_not_reparse_or_rewrite_the_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yoke_harness import codex_usage_attestation

    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [codex_turn_context("priced"), codex_token_count(input_tokens=100)],
    )
    real_save = codex_usage_attestation.save_watermark
    real_scan = codex_usage_attestation.scan_rows
    saves: list[int] = []
    scans: list[tuple[int, int]] = []

    def counted_save(*args: object, **kwargs: object) -> None:
        saves.append(1)
        real_save(*args, **kwargs)

    def counted_scan(*args: object, **kwargs: object):
        result = real_scan(*args, **kwargs)
        scans.append((int(args[1]), result.bytes_read))
        return result

    monkeypatch.setattr(codex_usage_attestation, "save_watermark", counted_save)
    monkeypatch.setattr(codex_usage_attestation, "scan_rows", counted_scan)
    first = _read_codex(rollout, monkeypatch)
    first_size = rollout.stat().st_size
    unchanged = _read_codex(rollout, monkeypatch)
    append_rows(rollout, [{"type": "response_item", "payload": {"type": "message"}}])
    appended = _read_codex(rollout, monkeypatch)

    assert first.models == unchanged.models == appended.models
    assert len(saves) == 2
    assert scans[1] == (first_size, 0)
    assert scans[2][0] == first_size
    assert scans[2][1] == rollout.stat().st_size - first_size


def test_unrecoverable_usage_is_named_until_a_later_total_replaces_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", 300)
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("priced"),
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": "x" * 5_000},
                },
            },
        ],
    )

    missing = _read_codex(rollout, monkeypatch)
    append_rows(rollout, [codex_token_count(input_tokens=700, cached=200)])
    recovered = _read_codex(rollout, monkeypatch)

    assert missing.status == USAGE_UNAVAILABLE
    assert missing.reason == USAGE_GAP_REASON
    assert recovered.status == USAGE_PARTIAL
    assert recovered.reason == MODEL_HISTORY_GAP_REASON
    assert recovered.models[0].input == 500


def test_a_later_cumulative_total_recovers_tokens_but_not_missing_model_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_scan, "MAX_SCAN_BYTES", 250)
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("priced"),
            {"type": "event_msg", "payload": {"body": "x" * 1_500}},
            codex_token_count(input_tokens=500, cached=100, output=20),
        ],
    )

    usage = _read_codex(rollout, monkeypatch)
    for _ in range(12):
        if usage.models and usage.models[0].input == 400:
            break
        usage = _read_codex(rollout, monkeypatch)

    assert usage.status == USAGE_PARTIAL
    assert usage.reason == MODEL_HISTORY_GAP_REASON
    assert usage.models[0].input == 400
    assert session_cost(usage, lambda _model: _Price()).status == COST_PARTIAL


def test_a_resume_inside_a_skipped_record_never_parses_its_fragment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = write_rows(
        tmp_path / "rollout.jsonl",
        [
            {"type": "response_item", "payload": {"body": "x" * 1_000}},
            codex_token_count(input_tokens=321),
        ],
    )
    seen: list[dict] = []
    offset = 0
    for _ in range(10):
        result = scan_rows(
            artifact,
            offset,
            seen.append,
            max_scan_bytes=300,
            record_factory=codex_record_decoder,
        )
        offset = result.offset
        if result.caught_up:
            break

    assert [row["payload"].get("type") for row in seen] == ["token_count"]


def test_a_legacy_sticky_oversized_mark_is_recovered_by_a_bounded_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [codex_turn_context("priced"), codex_token_count(input_tokens=500)],
    )
    save_watermark(
        "legacy",
        rollout,
        ArtifactWatermark(
            offset=rollout.stat().st_size,
            totals={"latest": {"input": 1}, "models": ["priced"]},
            oversized=True,
        ),
    )

    usage = _read_codex(rollout, monkeypatch, session_id="legacy")
    mark = load_watermark("legacy", rollout)

    assert usage.status == USAGE_COMPLETE
    assert usage.models[0].input == 500
    assert not mark.oversized
    assert mark.offset == rollout.stat().st_size


def test_model_facts_recover_from_a_large_irrelevant_field_but_not_a_lost_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", 300)
    recoverable = write_rows(
        tmp_path / "recoverable.jsonl",
        [
            {
                "payload": {"filler": "x" * 8_000, "model": "gpt-5"},
                "type": "turn_context",
            }
        ],
    )
    lost = write_rows(
        tmp_path / "lost.jsonl",
        [{"type": "turn_context", "payload": {"model": "m" * 5_000}}],
    )

    assert _codex_rollout_facts(recoverable, "recoverable").model == "gpt-5"
    assert not _codex_rollout_facts(lost, "lost").attested()


@dataclass(frozen=True)
class _Price:
    input_per_million_usd: Optional[float] = 1.0
    output_per_million_usd: Optional[float] = 5.0
    cache_read_per_million_usd: Optional[float] = 0.5
    cache_write_per_million_usd: Optional[float] = 2.0
    cache_write_long_per_million_usd: Optional[float] = 3.0
    conditions: str = "fixture"
    source_url: str = "https://example.invalid/pricing"
    effective_at: str = "2026-09-01"
    checked_at: str = "2026-09-10"
