"""What a Codex fold does about a record it could not read.

A rollout record that cannot be projected costs one of two things, never
both at once: the cumulative token statement it carried, which the next
statement restores outright, or the model that turn ran under, which
nothing later restores and which only pricing needs. These tests keep
that distinction honest, and cover the one-time rescan that lets a stored
record written by an earlier reader be folded again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from yoke_contracts.session_usage_cost import COST_COMPLETE, session_cost
from yoke_contracts.session_usage_facts import USAGE_COMPLETE, USAGE_UNAVAILABLE
from yoke_harness import artifact_scan
from yoke_harness.artifact_watermark import (
    ArtifactWatermark,
    load_watermark,
    save_watermark,
)
from yoke_harness.codex_usage_attestation import (
    MODEL_HISTORY_GAP_REASON,
    USAGE_GAP_REASON,
)
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
    session_id: str = "codex-1",
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
    # A replacing total covers the whole thread, so the counts are exact
    # again and only the model history stays lost.
    assert recovered.status == USAGE_COMPLETE
    assert recovered.cost_caveat == MODEL_HISTORY_GAP_REASON
    assert recovered.models[0].input == 500


def test_a_record_wider_than_one_scan_costs_the_history_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Abandoning it left the offset inside the record, so the turn after
    it was skipped too and the model history read incomplete for life."""
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

    assert usage.status == USAGE_COMPLETE
    assert not usage.cost_caveat
    assert usage.models[0].model == "priced"
    assert usage.models[0].input == 400
    assert session_cost(usage, lambda _model: _Price()).status == COST_COMPLETE


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
