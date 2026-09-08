"""Read back the tokens a provider actually charged a harness session.

One entry point, :func:`attest_session_usage`, dispatches to the artifact
each harness writes for itself, exactly as model attestation does. Every
branch answers only from that artifact and converts its source's
semantics into the shared disjoint buckets before returning, so nothing
downstream has to remember which provider counts what.

What each harness reports, measured rather than assumed:

* **claude** — every assistant row of its transcript carries a
  ``message.usage`` block stating uncached input, cache reads, cache
  writes split by cache lifetime, output, and the thinking tokens inside
  that output. One logical response is written as several rows sharing a
  ``message.id`` and repeating the same usage, so summing rows would
  multiply a turn's cost by its content-block count; the id is the dedup
  key that prevents it.
* **codex** — its rollout carries ``token_count`` events whose
  ``info.total_token_usage`` is cumulative for the thread, so the newest
  one is the whole answer and nothing accumulates. Its input count
  contains its cached input and its output count contains its reasoning,
  both of which are subtracted out into their own buckets here.
* **cursor** — optional ``stop`` / ``afterAgentResponse`` token fields
  (inclusive ``input_tokens``) and print-mode result ``usage`` (exclusive
  ``inputTokens``). A payload that omits them is not zero: the watermarked
  total is returned when one exists, otherwise ``unavailable`` for that
  surface. Same ``generation_id`` / ``request_id`` is counted once.

Reads resume from a per-session watermark, so a hook event folds only
what the artifact gained since the last one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_contracts.session_usage_facts import (
    USAGE_FIELDS,
    USAGE_COMPLETE,
    ModelUsage,
    SessionUsage,
    normalize_count,
    unavailable,
    with_partial,
)
from yoke_contracts.session_usage_sources import usage_source
from yoke_harness.usage_watermark import (
    UsageWatermark,
    load_watermark,
    read_new_lines,
    resolve_json_rows,
    save_watermark,
    stored_totals,
    truncation_reason,
)


#: Recorded when a harness states session-wide totals but ran more than
#: one model, so the totals cannot be divided between them.
MIXED_MODEL_REASON = (
    "this harness states one session-wide total and more than one model "
    "served the session, so consumption cannot be attributed per model"
)

#: Recorded when an artifact exists but has not yet stated any usage.
NO_USAGE_YET_REASON = "the harness artifact states no consumption yet"

#: Recorded when the artifact naming this session cannot be found.
NO_ARTIFACT_REASON = "no harness artifact was found for this session"


def attest_session_usage(
    executor: str,
    payload: Mapping[str, Any],
    *,
    transcript_path: str = "",
) -> SessionUsage:
    """Return the consumption this session's own artifact proves."""
    from yoke_harness.hooks.identity_runtime import is_claude, is_codex, is_cursor

    try:
        if is_cursor(executor):
            from yoke_harness.cursor_usage_attestation import attest_cursor_usage

            return attest_cursor_usage(payload)
        session_id = _text(payload.get("session_id"))
        if is_codex(executor):
            return _codex_usage(payload, session_id)
        if is_claude(executor):
            return _claude_usage(payload, session_id, transcript_path)
    except Exception:  # noqa: BLE001 — an unreadable source attests nothing
        return unavailable("the harness artifact could not be read")
    return unavailable(f"no usage source is declared for {executor}")


def _claude_usage(
    payload: Mapping[str, Any], session_id: str, transcript_path: str
) -> SessionUsage:
    """Fold a Claude transcript's per-message usage into per-model totals."""
    source = usage_source("claude")
    path = _artifact(transcript_path or _text(payload.get("transcript_path")))
    if path is None:
        return unavailable(NO_ARTIFACT_REASON, source=source)
    mark = load_watermark(session_id, path)
    lines, offset = read_new_lines(path, mark)
    totals = _totals_by_model(stored_totals(mark))
    last_key = mark.last_key
    for row in resolve_json_rows(lines):
        if row.get("type") != "assistant":
            continue
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        key = _text(message.get("id")) or _text(row.get("requestId"))
        if not key or key == last_key:
            continue
        model = _text(message.get("model"))
        usage = message.get("usage")
        if not model or not isinstance(usage, dict):
            continue
        last_key = key
        _accumulate(totals, model, _claude_buckets(usage))
    mark = UsageWatermark(
        offset=offset,
        last_key=last_key,
        totals=_totals_document(totals),
        truncated=mark.truncated,
    )
    save_watermark(session_id, path, mark)
    return _reading(totals, source=source, partial=truncation_reason(mark))


def _claude_buckets(usage: Mapping[str, Any]) -> dict[str, int]:
    """Convert one Claude usage block into the shared disjoint buckets.

    ``cache_creation`` states the same write total as
    ``cache_creation_input_tokens`` broken out by cache lifetime, so
    exactly one of the two is read: the split when it is present, because
    the lifetimes are billed at different rates, and the flat total
    otherwise. Reading both would count every cache write twice.
    """
    creation = usage.get("cache_creation")
    details = usage.get("output_tokens_details")
    if isinstance(creation, dict):
        short = normalize_count(creation.get("ephemeral_5m_input_tokens"))
        long_lived = normalize_count(creation.get("ephemeral_1h_input_tokens"))
    else:
        short = normalize_count(usage.get("cache_creation_input_tokens"))
        long_lived = 0
    return {
        "input": normalize_count(usage.get("input_tokens")),
        "cached_input": normalize_count(usage.get("cache_read_input_tokens")),
        "cache_write": short,
        "cache_write_long": long_lived,
        "output": normalize_count(usage.get("output_tokens")),
        "reasoning": normalize_count(
            details.get("thinking_tokens") if isinstance(details, dict) else None
        ),
    }


def _codex_usage(payload: Mapping[str, Any], session_id: str) -> SessionUsage:
    """Read a Codex rollout's newest cumulative total.

    Nothing accumulates here: ``total_token_usage`` already covers the
    whole thread, so the newest statement replaces the previous one and a
    read that finds no new statement keeps what it had.
    """
    from yoke_harness.hooks.identity_codex_runtime import codex_transcript_candidates
    from yoke_harness.hooks.identity_runtime import resolve_session_id
    import json as _json

    source = usage_source("codex")
    thread_id = _text(payload.get("thread_id")) or resolve_session_id(
        _json.dumps(dict(payload))
    )
    candidates = codex_transcript_candidates(thread_id) if thread_id else []
    path = candidates[0] if candidates else None
    if path is None:
        return unavailable(NO_ARTIFACT_REASON, source=source)
    mark = load_watermark(session_id, path)
    lines, offset = read_new_lines(path, mark)
    stored = stored_totals(mark)
    latest = stored.get("latest") if isinstance(stored.get("latest"), dict) else None
    models = [str(name) for name in stored.get("models", []) if str(name).strip()]
    for row in resolve_json_rows(lines):
        block = row.get("payload")
        if not isinstance(block, dict):
            continue
        if row.get("type") == "turn_context":
            model = _text(block.get("model"))
            if model and model not in models:
                models.append(model)
            continue
        if block.get("type") != "token_count":
            continue
        totals = _codex_totals(block)
        if totals is not None:
            latest = totals
    mark = UsageWatermark(
        offset=offset,
        last_key=mark.last_key,
        totals={"latest": latest or {}, "models": models},
        truncated=mark.truncated,
    )
    save_watermark(session_id, path, mark)
    if not latest:
        return _empty_reading(source, truncation_reason(mark))
    reading = _reading(
        {(models[-1] if models else ""): dict(latest)},
        source=source,
        partial=truncation_reason(mark),
    )
    if len(models) > 1:
        reading = with_partial(reading, MIXED_MODEL_REASON)
    return reading


def _codex_totals(block: Mapping[str, Any]) -> Optional[dict[str, int]]:
    """Convert one cumulative Codex reading into disjoint buckets.

    Codex's ``input_tokens`` contains its ``cached_input_tokens`` and its
    ``output_tokens`` contains its ``reasoning_output_tokens``, so the
    cached half is subtracted out into its own bucket while reasoning
    stays a labelled subset of the output it is already part of.
    """
    info = block.get("info")
    usage = info.get("total_token_usage") if isinstance(info, dict) else None
    if not isinstance(usage, dict):
        return None
    total_input = normalize_count(usage.get("input_tokens"))
    cached = min(normalize_count(usage.get("cached_input_tokens")), total_input)
    return {
        "input": total_input - cached,
        "cached_input": cached,
        "cache_write": normalize_count(usage.get("cache_write_input_tokens")),
        "cache_write_long": 0,
        "output": normalize_count(usage.get("output_tokens")),
        "reasoning": normalize_count(usage.get("reasoning_output_tokens")),
    }


def _reading(
    totals: dict[str, dict[str, int]], *, source: str, partial: Optional[str]
) -> SessionUsage:
    """Compose one reading from folded per-model totals."""
    models = tuple(
        ModelUsage(
            model=model, **{field: counts.get(field, 0) for field in USAGE_FIELDS}
        )
        for model, counts in totals.items()
        if model
    )
    if not models:
        return _empty_reading(source, partial)
    reading = SessionUsage(
        status=USAGE_COMPLETE,
        observed_at=_observed_at(),
        source=source,
        models=models,
    )
    return with_partial(reading, partial) if partial else reading


def _empty_reading(source: str, partial: Optional[str]) -> SessionUsage:
    """An artifact that exists but has stated nothing yet."""
    return unavailable(partial or NO_USAGE_YET_REASON, source=source)


def _totals_by_model(stored: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    models = stored.get("models")
    if not isinstance(models, dict):
        return {}
    return {
        str(model): {
            field: normalize_count(counts.get(field)) for field in USAGE_FIELDS
        }
        for model, counts in models.items()
        if isinstance(counts, dict)
    }


def _totals_document(totals: Mapping[str, dict[str, int]]) -> dict[str, Any]:
    return {"models": {model: dict(counts) for model, counts in totals.items()}}


def _accumulate(
    totals: dict[str, dict[str, int]], model: str, counts: Mapping[str, int]
) -> None:
    entry = totals.setdefault(model, {field: 0 for field in USAGE_FIELDS})
    for field in USAGE_FIELDS:
        entry[field] += counts.get(field, 0)


def _artifact(path: str) -> Optional[Path]:
    if not path:
        return None
    resolved = Path(path)
    return resolved if resolved.is_file() else None


def _observed_at() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "MIXED_MODEL_REASON",
    "NO_ARTIFACT_REASON",
    "NO_USAGE_YET_REASON",
    "attest_session_usage",
]
