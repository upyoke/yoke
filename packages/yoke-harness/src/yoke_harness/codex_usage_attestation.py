"""Read back the tokens Codex charged one thread.

Codex states consumption as ``token_count`` rollout events whose
``info.total_token_usage`` is cumulative for the whole thread, so nothing
accumulates here: the newest statement replaces the previous one, and a
read that finds no new statement keeps what it had. Its input count
contains its cached input and its output count contains its reasoning,
both of which are converted into the shared disjoint buckets.

Reading resumes from the same per-session watermark every harness reader
uses, under the same one-fold-at-a-time lock: a hook arriving while
another is folding answers from the persisted totals rather than
scanning the rollout a second time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_contracts.harness_family_identity import CODEX_FAMILY
from yoke_contracts.session_usage_facts import (
    SessionUsage,
    normalize_count,
    unavailable,
    with_partial,
)
from yoke_contracts.session_usage_sources import usage_source
from yoke_harness.artifact_scan import scan_rows
from yoke_harness.codex_artifact_reader import (
    MODEL_HISTORY_INCOMPLETE_KEY,
    USAGE_INCOMPLETE_KEY,
    codex_record_decoder,
    prepare_codex_watermark,
    stamp_codex_reader,
)
from yoke_harness.artifact_watermark import (
    ArtifactWatermark,
    load_watermark,
    partial_reason,
    save_watermark,
    stored_totals,
    watermark_lock,
)
from yoke_harness.usage_attestation import (
    NO_ARTIFACT_REASON,
    _empty_reading,
    _reading,
    _text,
)


#: Recorded when a harness states session-wide totals but ran more than
#: one model, so the totals cannot be divided between them.
MIXED_MODEL_REASON = (
    "this harness states one session-wide total and more than one model "
    "served the session, so consumption cannot be attributed per model"
)
USAGE_GAP_REASON = (
    "a Codex rollout record could not be projected, so its cumulative token "
    "statement is unavailable until a later total replaces it"
)
MODEL_HISTORY_GAP_REASON = (
    "a Codex rollout record could not be projected, so the session's model "
    "history and API-equivalent cost cannot be known exactly"
)


def attest_codex_usage(payload: Mapping[str, Any], session_id: str) -> SessionUsage:
    """Read a Codex rollout's newest cumulative total.

    Nothing accumulates here: ``total_token_usage`` already covers the
    whole thread, so the newest statement replaces the previous one and a
    read that finds no new statement keeps what it had.
    """
    from yoke_harness.hooks.identity_codex_runtime import codex_transcript_candidates
    from yoke_harness.hooks.identity_runtime import resolve_session_id
    import json as _json

    source = usage_source(CODEX_FAMILY)
    thread_id = _text(payload.get("thread_id")) or resolve_session_id(
        _json.dumps(dict(payload))
    )
    candidates = codex_transcript_candidates(thread_id) if thread_id else []
    path = candidates[0] if candidates else None
    if path is None:
        return unavailable(NO_ARTIFACT_REASON, source=source)
    with watermark_lock(session_id) as folding:
        if not folding:
            return _persisted_codex_reading(session_id, path, source)
        persisted_mark = load_watermark(session_id, path)
        mark = prepare_codex_watermark(persisted_mark)
        stored = stored_totals(mark)
        state: dict[str, Any] = {
            "latest": stored.get("latest")
            if isinstance(stored.get("latest"), dict)
            else None,
            "models": [
                str(name) for name in stored.get("models", []) if str(name).strip()
            ],
            USAGE_INCOMPLETE_KEY: bool(stored.get(USAGE_INCOMPLETE_KEY)),
            MODEL_HISTORY_INCOMPLETE_KEY: bool(
                stored.get(MODEL_HISTORY_INCOMPLETE_KEY)
            ),
        }

        def mark_gap() -> None:
            state[USAGE_INCOMPLETE_KEY] = True
            state[MODEL_HISTORY_INCOMPLETE_KEY] = True

        def fold(row: Mapping[str, Any]) -> None:
            block = row.get("payload")
            if not isinstance(block, dict):
                return
            if row.get("type") == "turn_context":
                model = _text(block.get("model"))
                if model and model not in state["models"]:
                    state["models"].append(model)
                return
            if block.get("type") != "token_count":
                return
            totals = _codex_totals(block)
            if totals is not None:
                state["latest"] = totals
                state[USAGE_INCOMPLETE_KEY] = False

        scan = scan_rows(
            path,
            mark.offset,
            fold,
            record_factory=codex_record_decoder,
            on_unrecoverable=mark_gap,
        )
        mark = ArtifactWatermark(
            offset=scan.offset,
            last_key=mark.last_key,
            totals=stamp_codex_reader(
                {
                    "latest": state["latest"] or {},
                    "models": state["models"],
                    USAGE_INCOMPLETE_KEY: state[USAGE_INCOMPLETE_KEY],
                    MODEL_HISTORY_INCOMPLETE_KEY: state[MODEL_HISTORY_INCOMPLETE_KEY],
                }
            ),
            truncated=mark.truncated,
            oversized=bool(
                state[USAGE_INCOMPLETE_KEY] or state[MODEL_HISTORY_INCOMPLETE_KEY]
            ),
            caught_up=scan.caught_up,
        )
        if mark != persisted_mark:
            save_watermark(session_id, path, mark)
    stored = stored_totals(mark)
    return _codex_reading(stored, source, _codex_partial_reason(stored, mark))


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


def _codex_reading(
    stored: Mapping[str, Any], source: str, partial: Optional[str]
) -> SessionUsage:
    """Present a Codex fold: its newest cumulative statement, per model."""
    latest = stored.get("latest") if isinstance(stored.get("latest"), dict) else None
    models = [str(name) for name in stored.get("models", []) if str(name).strip()]
    if not latest:
        return _empty_reading(source, partial)
    reading = _reading(
        {(models[-1] if models else ""): dict(latest)},
        source=source,
        partial=partial,
    )
    if len(models) > 1:
        reading = with_partial(reading, MIXED_MODEL_REASON)
    return reading


def _persisted_codex_reading(session_id: str, path: Path, source: str) -> SessionUsage:
    mark = load_watermark(session_id, path)
    stored = stored_totals(mark)
    return _codex_reading(stored, source, _codex_partial_reason(stored, mark))


def _codex_partial_reason(
    stored: Mapping[str, Any], mark: ArtifactWatermark
) -> Optional[str]:
    if mark.truncated:
        return partial_reason(mark)
    if stored.get(USAGE_INCOMPLETE_KEY):
        return USAGE_GAP_REASON
    if stored.get(MODEL_HISTORY_INCOMPLETE_KEY):
        return MODEL_HISTORY_GAP_REASON
    return partial_reason(mark)


__all__ = [
    "MIXED_MODEL_REASON",
    "MODEL_HISTORY_GAP_REASON",
    "USAGE_GAP_REASON",
    "attest_codex_usage",
]
