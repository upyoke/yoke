"""Tests for codex_model.py — Codex model resolver.

Covers: transcript scanning, cache reading, full resolution chain, and CLI.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import project_scratch_dir
from runtime.harness.codex.codex_model import (
    resolve,
    resolve_entrypoint,
    resolve_entrypoint_from_env,
    resolve_entrypoint_from_cache,
    resolve_entrypoint_from_transcript,
    resolve_from_cache,
    resolve_from_transcript,
)
from runtime.api.test_constants import TEST_MODEL_ID


def _helper_cache_path(thread_id: str):
    """Helper-resolved Codex model-cache path used by the resolver.

    Mirrors codex_hooks_payload.runtime_cache_path so the test writer and
    the production reader land on the same path.
    """
    return project_scratch_dir.harness_runtime_cache_path(
        f"codex-runtime-{thread_id}.json"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def transcript_dir(tmp_path, monkeypatch):
    """Create a fake Codex session transcript directory."""
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return sessions


@pytest.fixture
def cache_file(tmp_path, monkeypatch):
    """Create a fake hook cache file at the helper-resolved location."""
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    thread_id = "test-thread-abc123"
    cache_path = _helper_cache_path(thread_id)
    cache_path.write_text(json.dumps({"model": "o3-pro", "session_id": thread_id}))
    return thread_id, cache_path, tmp_path


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestResolveFromTranscript:
    def test_finds_model_in_transcript(self, transcript_dir):
        thread_id = "thread-xyz"
        transcript = transcript_dir / f"{thread_id}.jsonl"
        lines = [
            json.dumps({"type": "turn_context", "payload": {"model": "o3"}}),
            json.dumps({"type": "turn_context", "payload": {"model": "o3-pro"}}),
        ]
        transcript.write_text("\n".join(lines))

        result = resolve_from_transcript(thread_id)
        assert result == "o3-pro"

    def test_returns_none_when_no_transcript(self, transcript_dir):
        assert resolve_from_transcript("nonexistent-thread") is None

    def test_skips_non_turn_context(self, transcript_dir):
        thread_id = "thread-skip"
        transcript = transcript_dir / f"{thread_id}.jsonl"
        lines = [
            json.dumps({"type": "other", "payload": {"model": "wrong"}}),
        ]
        transcript.write_text("\n".join(lines))

        assert resolve_from_transcript(thread_id) is None


class TestResolveEntrypointFromTranscript:
    def test_normalizes_originator(self, transcript_dir):
        thread_id = "thread-entrypoint"
        transcript = transcript_dir / f"{thread_id}.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "originator": "Codex Desktop",
                        "source": "vscode",
                    },
                }
            )
        )

        assert resolve_entrypoint_from_transcript(thread_id) == "codex-desktop"

    def test_falls_back_to_source_when_originator_missing(self, transcript_dir):
        thread_id = "thread-source-only"
        transcript = transcript_dir / f"{thread_id}.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "source": "cli",
                    },
                }
            )
        )

        assert resolve_entrypoint_from_transcript(thread_id) == "cli"


class TestResolveFromCache:
    def test_reads_cache(self, cache_file):
        thread_id, _, _ = cache_file
        result = resolve_from_cache(thread_id)
        assert result == "o3-pro"

    def test_returns_none_when_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        assert resolve_from_cache("nonexistent") is None


class TestResolveEntrypointFromCache:
    def test_reads_cache_entrypoint(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        thread_id = "entrypoint-thread"
        cache_path = _helper_cache_path(thread_id)
        cache_path.write_text(
            json.dumps({"entrypoint": "codex-desktop", "session_id": thread_id})
        )
        assert resolve_entrypoint_from_cache(thread_id) == "codex-desktop"

    def test_normalizes_cache_originator_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
        thread_id = "originator-thread"
        cache_path = _helper_cache_path(thread_id)
        cache_path.write_text(
            json.dumps({"originator": "Codex Desktop", "session_id": thread_id})
        )
        assert resolve_entrypoint_from_cache(thread_id) == "codex-desktop"


class TestResolveEntrypointFromEnv:
    def test_normalizes_internal_originator_override(self, monkeypatch):
        monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")
        monkeypatch.delenv("CODEX_ORIGINATOR", raising=False)

        assert resolve_entrypoint_from_env() == "codex-desktop"

    def test_falls_back_to_codex_originator(self, monkeypatch):
        monkeypatch.delenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", raising=False)
        monkeypatch.setenv("CODEX_ORIGINATOR", "Codex CLI")

        assert resolve_entrypoint_from_env() == "codex-cli"

    def test_internal_override_wins_over_originator(self, monkeypatch):
        # CODEX_INTERNAL_ORIGINATOR_OVERRIDE outranks
        # CODEX_ORIGINATOR when both are set.
        monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "codex_vscode")
        monkeypatch.setenv("CODEX_ORIGINATOR", "codex_cli")

        assert resolve_entrypoint_from_env() == "codex-vscode"

    def test_returns_none_when_both_env_vars_absent(self, monkeypatch):
        monkeypatch.delenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", raising=False)
        monkeypatch.delenv("CODEX_ORIGINATOR", raising=False)

        assert resolve_entrypoint_from_env() is None


class TestResolve:
    def test_env_yoke_model_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("YOKE_MODEL", TEST_MODEL_ID)
        assert resolve() == TEST_MODEL_ID

    def test_env_codex_model_second(self, monkeypatch):
        monkeypatch.delenv("YOKE_MODEL", raising=False)
        monkeypatch.setenv("CODEX_MODEL", "o3")
        assert resolve() == "o3"

    def test_returns_none_without_thread(self, monkeypatch):
        monkeypatch.delenv("YOKE_MODEL", raising=False)
        monkeypatch.delenv("CODEX_MODEL", raising=False)
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        assert resolve(thread_id=None) is None


class TestResolveEntrypoint:
    def test_returns_none_without_thread_or_env_originator(self, monkeypatch):
        monkeypatch.delenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", raising=False)
        monkeypatch.delenv("CODEX_ORIGINATOR", raising=False)
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        assert resolve_entrypoint(thread_id=None) is None

    def test_env_originator_wins_without_thread(self, monkeypatch):
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")

        assert resolve_entrypoint(thread_id=None) == "codex-desktop"

    def test_resolves_from_transcript(self, transcript_dir):
        thread_id = "entrypoint-resolve"
        transcript = transcript_dir / f"{thread_id}.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "originator": "Codex Desktop",
                        "source": "vscode",
                    },
                }
            )
        )

        assert resolve_entrypoint(thread_id=thread_id) == "codex-desktop"
