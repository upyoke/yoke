"""Session-wide Codex totals, and Cursor's declared absence of any."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.harness_family_identity import CODEX_FAMILY
from yoke_contracts.session_usage_facts import USAGE_PARTIAL, USAGE_UNAVAILABLE
from yoke_contracts.session_usage_sources import states_usage, usage_source
from yoke_harness.codex_usage_attestation import MIXED_MODEL_REASON
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


def test_codex_cached_input_is_subtracted_out_of_its_input_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex states one input number that already contains its cached half."""
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("gpt-5.1-codex-max"),
            codex_token_count(input_tokens=1_000, cached=900, output=50, reasoning=20),
        ],
    )

    usage = _read_codex(rollout, monkeypatch)

    entry = usage.models[0]
    assert entry.input == 100
    assert entry.cached_input == 900
    assert entry.output == 50
    assert entry.reasoning == 20
    assert usage.billable_tokens() == 100 + 900 + 50
    assert usage.source == usage_source(CODEX_FAMILY)
    assert usage.source


def test_a_cached_count_larger_than_its_input_total_never_goes_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("gpt-5.1-codex-max"),
            codex_token_count(input_tokens=100, cached=500, output=10),
        ],
    )

    usage = _read_codex(rollout, monkeypatch)

    assert usage.models[0].input == 0
    assert usage.models[0].cached_input == 100


def test_codex_totals_are_cumulative_so_the_newest_one_replaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("gpt-5.1-codex-max"),
            codex_token_count(input_tokens=100, output=10),
            codex_token_count(input_tokens=500, output=50),
        ],
    )

    usage = _read_codex(rollout, monkeypatch)

    assert usage.models[0].input == 500
    assert usage.models[0].output == 50


def test_a_resumed_codex_read_keeps_the_last_cumulative_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("gpt-5.1-codex-max"),
            codex_token_count(input_tokens=500, output=50),
        ],
    )
    _read_codex(rollout, monkeypatch)
    append_rows(rollout, [{"type": "response_item", "payload": {"type": "message"}}])

    usage = _read_codex(rollout, monkeypatch)

    assert usage.models[0].input == 500


def test_codex_session_wide_totals_cannot_be_split_across_two_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            codex_turn_context("gpt-5.1-codex"),
            codex_token_count(input_tokens=100, output=10),
            codex_turn_context("gpt-5.1-codex-max"),
            codex_token_count(input_tokens=500, output=50),
        ],
    )

    usage = _read_codex(rollout, monkeypatch)

    assert usage.status == USAGE_PARTIAL
    assert usage.reason == MIXED_MODEL_REASON
    assert usage.billable_tokens() == 550


def test_a_codex_rollout_with_no_reading_yet_reports_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl", [codex_turn_context("gpt-5.1-codex-max")]
    )

    usage = _read_codex(rollout, monkeypatch)

    assert usage.status == USAGE_UNAVAILABLE
    assert usage.source == usage_source(CODEX_FAMILY)
    assert usage.source


def test_cursor_declares_a_usage_source_and_omitted_fields_are_unavailable() -> None:
    usage = attest_session_usage("cursor", {"session_id": "cursor-1"})

    assert states_usage("cursor") is True
    assert usage.status == USAGE_UNAVAILABLE
    assert "cursor" in usage.reason
    assert "unsupported" not in usage.reason
