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
  key that prevents it. A transcript row can also be enormous — a pasted
  file, a tool result — so rows past the reader's record bound are
  projected down to those fields rather than skipped
  (:mod:`yoke_harness.claude_artifact_reader`).
* **codex** — its rollout carries cumulative ``token_count`` events, read
  by :mod:`yoke_harness.codex_usage_attestation`.
* **cursor** — optional ``stop`` / ``afterAgentResponse`` token fields
  (inclusive ``input_tokens``) and print-mode result ``usage`` (exclusive
  ``inputTokens``), the latter presented by the reader of a finished
  native's capture rather than by a hook. A payload that omits them is not
  zero: the watermarked total is returned when one exists, otherwise
  ``unavailable`` for that surface. Same ``generation_id`` / ``request_id``
  is counted once.

Three differences between those branches are deliberate, and each
follows from what its source actually states. Claude accumulates, so its
fold dedups per message and a replay must start from empty totals; Codex
does not accumulate at all, so its newest cumulative statement replaces
whatever is held and a lost record costs the model history rather than
the counts; Cursor is folded from payloads handed to this process once,
so its reader waits for the lock rather than yielding it, and a payload
that omits the optional token fields is unavailable for that surface
rather than a zero.

Reads resume from a per-session watermark, so a hook event folds only
what the artifact gained since the last one, and each fold streams its
records under the shared byte bounds rather than holding a tail whose
size is the session's to choose. Only one fold per session runs at a
time: a second hook arriving mid-fold answers from the totals already
persisted instead of scanning the same bytes again.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_contracts.harness_family_identity import CLAUDE_FAMILY
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
from yoke_harness.artifact_scan import scan_rows
from yoke_harness.claude_artifact_reader import (
    ASSISTANT_ROW_TYPE,
    claude_record_decoder,
    prepare_claude_watermark,
    stamp_claude_reader,
)
from yoke_harness.artifact_watermark import (
    ArtifactWatermark,
    load_watermark,
    partial_reason,
    save_watermark,
    stored_totals,
    watermark_lock,
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
            from yoke_harness.codex_usage_attestation import attest_codex_usage

            return attest_codex_usage(payload, session_id)
        if is_claude(executor):
            return _claude_usage(payload, session_id, transcript_path)
    except Exception:  # noqa: BLE001 — an unreadable source attests nothing
        return unavailable("the harness artifact could not be read")
    return unavailable(f"no usage source is declared for {executor}")


def _claude_usage(
    payload: Mapping[str, Any], session_id: str, transcript_path: str
) -> SessionUsage:
    """Fold a Claude transcript's per-message usage into per-model totals.

    A gap here means one assistant row's usage statement could not be
    read. An oversized row of any other kind is not a gap: it states no
    consumption, so the projection that dropped its content dropped
    nothing this fold was reading for.
    """
    source = usage_source(CLAUDE_FAMILY)
    path = _artifact(transcript_path or _text(payload.get("transcript_path")))
    if path is None:
        return unavailable(NO_ARTIFACT_REASON, source=source)
    with watermark_lock(session_id) as folding:
        if not folding:
            return _persisted_reading(session_id, path, source)
        mark = prepare_claude_watermark(load_watermark(session_id, path))
        totals = _totals_by_model(stored_totals(mark))
        state: dict[str, Any] = {"last_key": mark.last_key, "gap": mark.oversized}

        def mark_gap() -> None:
            state["gap"] = True

        def fold(row: Mapping[str, Any]) -> None:
            if row.get("type") != ASSISTANT_ROW_TYPE:
                return
            message = row.get("message")
            if not isinstance(message, dict):
                return
            key = _text(message.get("id")) or _text(row.get("requestId"))
            if not key or key == state["last_key"]:
                return
            model = _text(message.get("model"))
            usage = message.get("usage")
            if not model or not isinstance(usage, dict):
                return
            state["last_key"] = key
            _accumulate(totals, model, _claude_buckets(usage))

        scan = scan_rows(
            path,
            mark.offset,
            fold,
            record_factory=claude_record_decoder,
            on_unrecoverable=mark_gap,
        )
        mark = ArtifactWatermark(
            offset=scan.offset,
            last_key=state["last_key"],
            totals=stamp_claude_reader(_totals_document(totals)),
            truncated=mark.truncated,
            oversized=bool(state["gap"]),
            caught_up=scan.caught_up,
        )
        save_watermark(session_id, path, mark)
    return _reading(totals, source=source, partial=partial_reason(mark))


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


def _persisted_reading(session_id: str, path: Path, source: str) -> SessionUsage:
    """The totals a concurrent fold already persisted, folding nothing."""
    mark = load_watermark(session_id, path)
    return _reading(
        _totals_by_model(stored_totals(mark)),
        source=source,
        partial=partial_reason(mark),
    )


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
    "NO_ARTIFACT_REASON",
    "NO_USAGE_YET_REASON",
    "attest_session_usage",
]
