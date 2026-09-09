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


def test_a_settled_session_keeps_resolving_while_its_fold_is_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The marker ends the reads; a fold that is behind reopens them.

    A settled session resolves only on registration events, so a bounded
    fold left to those alone would advance once per user prompt and keep
    reporting the model it shipped long after a later turn changed it.
    """
    from yoke_harness.hooks import identity_codex_runtime
    from yoke_harness.hooks.identity_model_facts import (
        client_model_facts,
        record_model_facts_shipped,
    )

    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [codex_turn_context("gpt-5")]
        + [{"type": "event_msg", "payload": {"filler": "a" * 2_000}}] * 4
        + [codex_turn_context("gpt-5-codex")],
    )
    monkeypatch.setattr(
        identity_codex_runtime, "codex_transcript_candidates", lambda _id: [rollout]
    )
    payload = {"session_id": "thread-1", "thread_id": "thread-1"}
    record_model_facts_shipped(payload, "gpt-5")

    with monkeypatch.context() as bounded:
        bounded.setattr(artifact_scan, "MAX_SCAN_BYTES", 600)
        assert client_model_facts("UserPromptSubmit", payload, "codex") == {}
        after_prompt = load_watermark("thread-1", rollout, kind=MODEL_KIND)
        assert not after_prompt.caught_up

        assert client_model_facts("PreToolUse", payload, "codex") == {}
        after_tool_call = load_watermark("thread-1", rollout, kind=MODEL_KIND)

    assert after_tool_call.offset > after_prompt.offset
    assert client_model_facts("PreToolUse", payload, "codex")["model"] == "gpt-5-codex"


def test_a_settled_session_whose_fold_caught_up_stops_reading_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yoke_harness.hooks import identity_codex_runtime
    from yoke_harness.hooks.identity_model_facts import (
        client_model_facts,
        record_model_facts_shipped,
    )

    rollout = write_rows(tmp_path / "rollout.jsonl", [codex_turn_context("gpt-5")])
    monkeypatch.setattr(
        identity_codex_runtime, "codex_transcript_candidates", lambda _id: [rollout]
    )
    payload = {"session_id": "thread-1", "thread_id": "thread-1"}
    client_model_facts("SessionStart", payload, "codex")
    record_model_facts_shipped(payload, "gpt-5")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a caught-up settled session must not read again")

    monkeypatch.setattr(identity_codex_runtime, "codex_transcript_candidates", refuse)

    assert client_model_facts("PreToolUse", payload, "codex") == {}


def test_a_harness_whose_model_read_is_current_is_never_behind(
    tmp_path: Path,
) -> None:
    """Claude reads a bounded tail, so there is no fold to fall behind."""
    from yoke_harness.model_attestation import served_facts_catching_up

    assert not served_facts_catching_up(
        "claude-code", {"session_id": "session-1", "transcript_path": "s.jsonl"}
    )
