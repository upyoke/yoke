"""Shared artifact builders for the session-usage attestation suites.

The row shapes here mirror what the harnesses actually write, because the
whole point of the reader under test is converting those exact shapes into
one set of buckets. Each builder therefore keeps the source's own field
names and its own overlaps — Claude's split cache-creation block, Codex's
input total that contains its cached half — rather than a tidied form the
reader would never meet in practice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep each test's resume watermarks out of the real machine home."""
    from yoke_cli.config import machine_config

    home = tmp_path / "yoke-home"
    home.mkdir()
    monkeypatch.setattr(machine_config, "yoke_home", lambda: home)
    return home


def write_rows(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def append_rows(path: Path, rows: list[dict]) -> None:
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def claude_row(
    message_id: str,
    model: str = "claude-opus-5",
    *,
    input_tokens: int = 10,
    output_tokens: int = 100,
    cache_read: int = 1_000,
    ephemeral_5m: int = 200,
    ephemeral_1h: int = 300,
    thinking: int = 40,
) -> dict:
    """One assistant row exactly as a Claude transcript stamps it.

    ``cache_creation_input_tokens`` and the ``cache_creation`` block state
    the same writes twice — the flat total beside its per-lifetime split —
    which is why the reader must choose one and never sum both.
    """
    return {
        "type": "assistant",
        "requestId": f"req_{message_id}",
        "message": {
            "id": message_id,
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": ephemeral_5m + ephemeral_1h,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": ephemeral_5m,
                    "ephemeral_1h_input_tokens": ephemeral_1h,
                },
                "output_tokens_details": {"thinking_tokens": thinking},
            },
        },
    }


def codex_token_count(
    *,
    input_tokens: int,
    cached: int = 0,
    cache_write: int = 0,
    output: int = 0,
    reasoning: int = 0,
) -> dict:
    """One cumulative Codex reading, with its documented field overlaps.

    ``input_tokens`` includes ``cached_input_tokens`` and ``output_tokens``
    includes ``reasoning_output_tokens``, so a reader that adds the fields
    as written counts the cached half twice.
    """
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached,
                    "cache_write_input_tokens": cache_write,
                    "output_tokens": output,
                    "reasoning_output_tokens": reasoning,
                }
            },
        },
    }


def codex_turn_context(model: str) -> dict:
    return {"type": "turn_context", "payload": {"model": model}}


def cursor_stop_payload(
    *,
    session_id: str = "cursor-1",
    generation_id: str = "gen-1",
    model: str = "composer-2",
    input_tokens: int = 100,
    output_tokens: int = 20,
    cache_read_tokens: int = 40,
    cache_write_tokens: int = 10,
    event: str = "stop",
) -> dict:
    """One Cursor ``stop`` payload with the staff-documented token fields.

    ``input_tokens`` is inclusive of both cache figures, matching the
    native hook shape rather than the print-mode result.
    """
    return {
        "hook_event_name": event,
        "session_id": session_id,
        "conversation_id": session_id,
        "generation_id": generation_id,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
    }


def cursor_result_payload(
    *,
    session_id: str = "cursor-1",
    request_id: str = "req-1",
    input_tokens: int = 6536,
    output_tokens: int = 34,
    cache_read_tokens: int = 7424,
    cache_write_tokens: int = 0,
) -> dict:
    """Print-mode result JSON: exclusive ``inputTokens``, no model name."""
    return {
        "type": "result",
        "subtype": "success",
        "session_id": session_id,
        "request_id": request_id,
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cacheReadTokens": cache_read_tokens,
            "cacheWriteTokens": cache_write_tokens,
        },
    }


__all__ = [
    "append_rows",
    "claude_row",
    "codex_token_count",
    "codex_turn_context",
    "cursor_result_payload",
    "cursor_stop_payload",
    "machine_home",
    "write_rows",
]
