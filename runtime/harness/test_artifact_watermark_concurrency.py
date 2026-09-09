"""One fold at a time, and a record that is never half-written.

The failures these cover were reproduced with tiny fixtures: a checkpoint
read during its own rewrite reported offset zero and replayed a whole
history, and two folds racing left the older offset written last. Both
are cheap to prove and expensive to meet.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_harness import artifact_watermark
from yoke_harness.artifact_watermark import (
    MODEL_KIND,
    ArtifactWatermark,
    load_watermark,
    partial_reason,
    save_watermark,
    stored_totals,
    watermark_lock,
    watermark_path,
)
from yoke_harness.model_attestation import _codex_rollout_facts
from yoke_harness.usage_attestation import attest_session_usage
from runtime.harness.session_usage_test_support import (  # noqa: F401
    append_rows,
    claude_row,
    codex_token_count,
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


def test_a_cold_record_resumes_from_the_beginning(tmp_path: Path) -> None:
    mark = load_watermark("session-1", tmp_path / "s.jsonl")

    assert mark.offset == 0
    assert stored_totals(mark) == {}


def test_an_interrupted_record_is_read_as_no_record_rather_than_crashing(
    tmp_path: Path,
) -> None:
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])
    _read_claude(transcript)
    record = watermark_path("session-1")
    record.write_text(record.read_text()[: len(record.read_text()) // 2])

    usage = _read_claude(transcript)

    assert usage.models[0].output == 100


def test_a_failed_save_leaves_the_previous_record_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacement is what a concurrent reader depends on: never a truncation."""
    artifact = tmp_path / "s.jsonl"
    save_watermark("session-1", artifact, ArtifactWatermark(offset=128, last_key="a"))

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError("replacement failed")

    with monkeypatch.context() as refusing:
        refusing.setattr(os, "replace", refuse)
        save_watermark(
            "session-1", artifact, ArtifactWatermark(offset=192, last_key="b")
        )

    survivor = load_watermark("session-1", artifact)
    assert survivor.offset == 128
    assert survivor.last_key == "a"


def test_a_failed_save_leaves_no_staged_file_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "s.jsonl"

    with monkeypatch.context() as refusing:
        refusing.setattr(
            os, "replace", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no"))
        )
        save_watermark("session-1", artifact, ArtifactWatermark(offset=64))

    assert list(watermark_path("session-1").parent.glob("*.staged")) == []


def test_only_one_holder_folds_at_a_time(tmp_path: Path) -> None:
    with watermark_lock("session-1") as first:
        with watermark_lock("session-1") as second:
            assert first is True
            assert second is False


def test_the_usage_and_model_folds_do_not_exclude_each_other(tmp_path: Path) -> None:
    """They advance over the same file independently, so they share no lock."""
    with watermark_lock("session-1"):
        with watermark_lock("session-1", kind=MODEL_KIND) as model_fold:
            assert model_fold is True


def test_a_contending_reader_answers_from_the_persisted_totals(
    tmp_path: Path,
) -> None:
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])
    first = _read_claude(transcript)
    append_rows(transcript, [claude_row("msg_b")])
    folded_through = load_watermark("session-1", transcript).offset

    with watermark_lock("session-1"):
        contender = _read_claude(transcript)

    assert contender.billable_tokens() == first.billable_tokens()
    assert load_watermark("session-1", transcript).offset == folded_through


def test_a_contending_reader_never_writes_an_older_offset(tmp_path: Path) -> None:
    """The regression a lock prevents that an atomic write alone cannot."""
    transcript = write_rows(tmp_path / "s.jsonl", [claude_row("msg_a")])
    _read_claude(transcript)
    append_rows(transcript, [claude_row("msg_b")])
    _read_claude(transcript)
    newest = load_watermark("session-1", transcript).offset

    with watermark_lock("session-1"):
        _read_claude(transcript)

    assert load_watermark("session-1", transcript).offset == newest


def test_codex_model_facts_fold_forward_without_rereading(tmp_path: Path) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [
            {
                "type": "turn_context",
                "payload": {"model": "gpt-5", "model_context_window": 400_000},
            }
        ],
    )

    first = _codex_rollout_facts(rollout, "thread-1")
    folded_through = load_watermark("thread-1", rollout, kind=MODEL_KIND).offset
    append_rows(rollout, [codex_turn_context("gpt-5-codex")])
    second = _codex_rollout_facts(rollout, "thread-1")

    assert first.model == "gpt-5"
    assert first.context_window_tokens == 400_000
    assert second.model == "gpt-5-codex"
    assert second.context_window_tokens == 400_000
    assert load_watermark("thread-1", rollout, kind=MODEL_KIND).offset > folded_through


def test_a_contending_model_reader_answers_from_the_record(tmp_path: Path) -> None:
    rollout = write_rows(tmp_path / "rollout.jsonl", [codex_turn_context("gpt-5")])
    _codex_rollout_facts(rollout, "thread-1")
    append_rows(rollout, [codex_turn_context("gpt-5-codex")])

    with watermark_lock("thread-1", kind=MODEL_KIND):
        contender = _codex_rollout_facts(rollout, "thread-1")

    assert contender.model == "gpt-5"


def test_a_truncated_rollout_restates_its_facts_from_the_beginning(
    tmp_path: Path,
) -> None:
    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [codex_turn_context("gpt-5"), codex_turn_context("gpt-5")],
    )
    _codex_rollout_facts(rollout, "thread-1")
    write_rows(tmp_path / "rollout.jsonl", [codex_turn_context("gpt-5-codex")])

    facts = _codex_rollout_facts(rollout, "thread-1")

    assert facts.model == "gpt-5-codex"


def test_a_codex_usage_fold_resumes_and_keeps_its_newest_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yoke_harness.hooks import identity_codex_runtime

    rollout = write_rows(
        tmp_path / "rollout.jsonl",
        [codex_turn_context("gpt-5"), codex_token_count(input_tokens=100)],
    )
    monkeypatch.setattr(
        identity_codex_runtime, "codex_transcript_candidates", lambda _id: [rollout]
    )
    payload = {"session_id": "session-1", "thread_id": "thread-1"}

    first = attest_session_usage("codex", payload)
    append_rows(rollout, [codex_token_count(input_tokens=250)])
    second = attest_session_usage("codex", payload)

    assert first.models[0].input == 100
    assert second.models[0].input == 250


def test_a_record_naming_another_artifact_is_not_this_ones_resume_point(
    tmp_path: Path,
) -> None:
    save_watermark("session-1", tmp_path / "old.jsonl", ArtifactWatermark(offset=512))

    mark = load_watermark("session-1", tmp_path / "new.jsonl")

    assert mark.offset == 0


def test_a_lock_file_older_than_the_prune_age_survives_a_save(
    tmp_path: Path,
) -> None:
    """A long session's lock is created once; pruning it would unlock a fold."""
    artifact = tmp_path / "s.jsonl"
    with watermark_lock("session-1"):
        pass
    record = watermark_path("session-1")
    lock = record.parent / f"{record.name}.lock"
    os.utime(lock, (0, 0))

    save_watermark("session-1", artifact, ArtifactWatermark(offset=1))

    assert lock.exists()


def test_a_stale_record_for_a_finished_session_is_pruned(tmp_path: Path) -> None:
    artifact = tmp_path / "s.jsonl"
    save_watermark("session-old", artifact, ArtifactWatermark(offset=1))
    stale = watermark_path("session-old")
    os.utime(stale, (0, 0))

    save_watermark("session-1", artifact, ArtifactWatermark(offset=1))

    assert not stale.exists()


def test_a_record_is_readable_json_after_every_save(tmp_path: Path) -> None:
    artifact = tmp_path / "s.jsonl"
    save_watermark(
        "session-1", artifact, ArtifactWatermark(offset=64, totals={"models": {}})
    )

    document = json.loads(watermark_path("session-1").read_text(encoding="utf-8"))

    assert document["offset"] == 64
    assert document["artifact"] == str(artifact)


def test_the_watermark_module_names_its_own_kinds(tmp_path: Path) -> None:
    """Usage and model records never collide on one session's file name."""
    assert watermark_path("session-1") != watermark_path("session-1", kind=MODEL_KIND)
    assert artifact_watermark.USAGE_KIND != MODEL_KIND
