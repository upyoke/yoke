"""Read Cursor parent-turn token counts from native hook and result payloads.

Cursor staff document optional ``input_tokens`` / ``output_tokens`` /
``cache_read_tokens`` / ``cache_write_tokens`` on ``stop`` and
``afterAgentResponse``. Those counts are cumulative for the parent turn,
identical across the two events for one ``generation_id``, and exclusive
of subagents. ``input_tokens`` already contains both cache figures, so
disjoint buckets subtract them and clamp the remainder at zero.

The installed CLI's print-mode JSON result is a second native shape:
``usage.inputTokens`` (exclusive of cache), ``cacheReadTokens``,
``cacheWriteTokens``, ``outputTokens``, keyed by ``request_id``. That result
reaches this reader from the finished native's own capture rather than from a
hook — a print-mode turn prints it as it exits, after its last hook has run,
and a 2026.09.02-c22c1a3 sample did not invoke ``stop`` at all
(``yoke_harness.cursor_native_result_usage``). Conversation store blobs still
carry no usage.

A payload that names no token fields is not a proof of zero: return the
watermarked total when one exists, otherwise ``unavailable`` for *this*
surface rather than a global Cursor deferral. Missing optional fields are
unknown, not fabricated zeros, so an incomplete set is not folded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_contracts.session_usage_facts import (
    SessionUsage,
    normalize_count,
    unavailable,
)
from yoke_contracts.session_usage_sources import (
    CURSOR_INCOMPLETE_TOKEN_FIELDS_REASON,
    CURSOR_NO_TURN_IDENTITY_REASON,
    UNNAMED_MODEL,
    CURSOR_USAGE_SOURCE,
    usage_source,
)
from yoke_harness.artifact_watermark import (
    ArtifactWatermark,
    load_watermark,
    save_watermark,
    stored_totals,
    watermark_lock,
)


#: How many parent-turn ids the dedup record keeps. A turn arrives twice
#: within moments — a ``stop`` and an ``afterAgentResponse`` naming one
#: ``generation_id`` — never after hundreds of later turns, so keeping
#: every id a long session ever produced would grow a record that is
#: rewritten on every turn to no purpose.
DEDUP_HISTORY = 512

_HOOK_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)
_RESULT_FIELDS = (
    "inputTokens",
    "outputTokens",
    "cacheReadTokens",
    "cacheWriteTokens",
)


def attest_cursor_usage(payload: Mapping[str, Any]) -> SessionUsage:
    """Fold one Cursor hook or print-mode result into session totals.

    The fold waits for its turn rather than yielding it: a Cursor payload
    states its turn's tokens exactly once, in this call, so a reader that
    answered from the persisted record instead would lose them entirely.
    The critical section is a small read and a small write, never an
    artifact scan.
    """
    with watermark_lock(_session_id(payload), blocking=True):
        return _fold_cursor_usage(payload)


def _fold_cursor_usage(payload: Mapping[str, Any]) -> SessionUsage:
    from yoke_harness.usage_attestation import (
        _accumulate,
        _reading,
        _totals_by_model,
        _totals_document,
    )

    source = usage_source("cursor") or CURSOR_USAGE_SOURCE
    session_id = _session_id(payload)
    artifact = Path("cursor-hooks") / (session_id or "unknown")
    mark = load_watermark(session_id, artifact)
    totals = _totals_by_model(stored_totals(mark))
    seen = _generation_ids(stored_totals(mark))
    if payload.get("is_subagent_session") is True:
        buckets, generation, model = None, "", ""
    else:
        buckets, generation, model = _payload_reading(payload)
    if buckets is not None and generation:
        if generation not in seen:
            _accumulate(totals, model, buckets)
            seen.append(generation)
            del seen[:-DEDUP_HISTORY]
        mark = ArtifactWatermark(
            last_key=generation,
            totals=_cursor_document(totals, seen, _totals_document),
        )
        save_watermark(session_id, artifact, mark)
    elif buckets is not None:
        return unavailable(CURSOR_NO_TURN_IDENTITY_REASON, source=source)
    elif (
        _token_keys_present(payload) and payload.get("is_subagent_session") is not True
    ):
        if totals:
            return _reading(totals, source=source, partial=None)
        return unavailable(CURSOR_INCOMPLETE_TOKEN_FIELDS_REASON, source=source)
    if totals:
        return _reading(totals, source=source, partial=None)
    return unavailable(_omitted_reason(payload), source=source)


def _payload_reading(
    payload: Mapping[str, Any],
) -> tuple[Optional[dict[str, int]], str, str]:
    """Return disjoint buckets, generation key, and model, or skip."""
    nested = payload.get("usage")
    if isinstance(nested, dict) and all(field in nested for field in _RESULT_FIELDS):
        return (
            {
                "input": normalize_count(nested.get("inputTokens")),
                "cached_input": normalize_count(nested.get("cacheReadTokens")),
                "cache_write": normalize_count(nested.get("cacheWriteTokens")),
                "cache_write_long": 0,
                "output": normalize_count(nested.get("outputTokens")),
                "reasoning": 0,
            },
            _text(payload.get("request_id")) or _text(payload.get("generation_id")),
            _model_name(payload, nested),
        )
    if all(field in payload for field in _HOOK_FIELDS):
        total_input = normalize_count(payload.get("input_tokens"))
        cached = normalize_count(payload.get("cache_read_tokens"))
        written = normalize_count(payload.get("cache_write_tokens"))
        uncached = total_input - cached - written
        if uncached < 0:
            uncached = 0
        return (
            {
                "input": uncached,
                "cached_input": cached,
                "cache_write": written,
                "cache_write_long": 0,
                "output": normalize_count(payload.get("output_tokens")),
                "reasoning": 0,
            },
            _text(payload.get("generation_id")) or _text(payload.get("request_id")),
            _model_name(payload, None),
        )
    return None, "", ""


def _token_keys_present(payload: Mapping[str, Any]) -> bool:
    nested = payload.get("usage")
    if isinstance(nested, dict) and any(field in nested for field in _RESULT_FIELDS):
        return True
    return any(field in payload for field in _HOOK_FIELDS)


def _model_name(payload: Mapping[str, Any], nested: Optional[Mapping[str, Any]]) -> str:
    for block in (payload, nested or {}):
        for key in ("model", "model_id", "modelName"):
            name = _text(block.get(key))
            if name:
                return name
    return UNNAMED_MODEL


def _session_id(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("session_id")) or _text(payload.get("conversation_id"))


def _generation_ids(stored: Mapping[str, Any]) -> list[str]:
    raw = stored.get("generations")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _cursor_document(
    totals: Mapping[str, dict[str, int]],
    seen: list[str],
    totals_document,
) -> dict[str, Any]:
    document = totals_document(totals)
    document["generations"] = list(seen)
    return document


def _omitted_reason(payload: Mapping[str, Any]) -> str:
    event = _text(payload.get("hook_event_name"))
    if event:
        return f"cursor {event} payload omitted token fields (they are optional)"
    if _text(payload.get("type")) == "result":
        return "cursor print-mode result omitted usage token fields"
    return "cursor payload omitted token fields (they are optional)"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["attest_cursor_usage"]
