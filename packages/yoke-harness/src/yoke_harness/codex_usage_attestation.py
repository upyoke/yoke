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
from yoke_harness.artifact_scan import CATCH_UP_PENDING_REASON, scan_rows
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


def attest_codex_usage(
    payload: Mapping[str, Any], session_id: str
) -> SessionUsage:
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
        mark = load_watermark(session_id, path)
        stored = stored_totals(mark)
        state: dict[str, Any] = {
            "latest": stored.get("latest")
            if isinstance(stored.get("latest"), dict)
            else None,
            "models": [
                str(name) for name in stored.get("models", []) if str(name).strip()
            ],
        }

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

        scan = scan_rows(path, mark.offset, fold)
        mark = ArtifactWatermark(
            offset=scan.offset,
            last_key=mark.last_key,
            totals={"latest": state["latest"] or {}, "models": state["models"]},
            truncated=mark.truncated,
            oversized=mark.oversized or scan.oversized,
        )
        save_watermark(session_id, path, mark)
    reading = _codex_reading(stored_totals(mark), source, partial_reason(mark))
    return reading if scan.caught_up else with_partial(reading, CATCH_UP_PENDING_REASON)


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


def _persisted_codex_reading(
    session_id: str, path: Path, source: str
) -> SessionUsage:
    mark = load_watermark(session_id, path)
    return _codex_reading(stored_totals(mark), source, partial_reason(mark))


__all__ = ["MIXED_MODEL_REASON", "attest_codex_usage"]
