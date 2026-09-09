"""Resolving Codex identity reads what it needs, once.

A thread's entrypoint is written when the thread is created and never
changes, and its model is whatever its newest turn names — so neither
answer justifies parsing a rollout that grows for the life of the
session, on every hook event it fires.
"""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path

import pytest

from yoke_cli.config import machine_config
from yoke_harness.artifact_scan import MAX_TAIL_BYTES
from yoke_harness.hooks import identity_codex_runtime


@pytest.fixture(autouse=True)
def machine_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep remembered thread metadata out of the real machine cache."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(machine_config, "cache_dir", lambda: cache)
    return cache


def _rollout(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def _bind(monkeypatch: pytest.MonkeyPatch, paths: list[Path]) -> None:
    monkeypatch.setattr(
        identity_codex_runtime, "codex_transcript_candidates", lambda _id: paths
    )


def _session_meta(originator: str) -> dict:
    return {"type": "session_meta", "payload": {"originator": originator}}


def _padded(size: int) -> dict:
    return {"type": "event_msg", "payload": {"filler": "a" * size}}


def test_the_entrypoint_scan_stops_at_the_row_that_states_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = _rollout(
        tmp_path / "t.jsonl",
        [_session_meta("codex_vscode")] + [_padded(200_000) for _ in range(6)],
    )
    _bind(monkeypatch, [rollout])

    tracemalloc.start()
    try:
        entrypoint = identity_codex_runtime._codex_entrypoint_from_transcript("t")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert entrypoint == "codex-vscode"
    assert peak < rollout.stat().st_size


def test_a_resolved_entrypoint_is_remembered_for_the_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Immutable metadata is read once; later events answer from the record."""
    rollout = _rollout(tmp_path / "t.jsonl", [_session_meta("codex_vscode")])
    _bind(monkeypatch, [rollout])
    assert identity_codex_runtime._codex_entrypoint_from_transcript("t") == (
        "codex-vscode"
    )

    _bind(monkeypatch, [])

    assert identity_codex_runtime._codex_entrypoint_from_transcript("t") == (
        "codex-vscode"
    )


def test_a_thread_whose_metadata_names_nothing_is_not_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = _rollout(tmp_path / "t.jsonl", [_padded(10)])
    _bind(monkeypatch, [rollout])

    assert identity_codex_runtime._codex_entrypoint_from_transcript("t") is None
    assert not identity_codex_runtime._entrypoint_cache_path("t").exists()


def test_the_model_comes_off_the_end_of_the_rollout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = _rollout(
        tmp_path / "t.jsonl",
        [{"type": "turn_context", "payload": {"model": "gpt-5"}}]
        + [_padded(200_000) for _ in range(6)]
        + [{"type": "turn_context", "payload": {"model": "gpt-5-codex"}}],
    )
    _bind(monkeypatch, [rollout])

    tracemalloc.start()
    try:
        model = identity_codex_runtime._codex_model_from_transcript("t")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert model == "gpt-5-codex"
    assert peak < 2 * MAX_TAIL_BYTES


def test_a_thread_with_no_transcript_resolves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind(monkeypatch, [])

    assert identity_codex_runtime._codex_model_from_transcript("t") is None
    assert identity_codex_runtime._codex_entrypoint_from_transcript("t") is None
