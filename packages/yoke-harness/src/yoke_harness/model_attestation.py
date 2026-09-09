"""Read back what a provider actually served a harness session.

One entry point, :func:`attest_served_facts`, dispatches to the artifact
each harness writes for itself. Every branch answers only from that
artifact: an unreadable, absent, or silent source yields ``None`` for the
fact it could not prove rather than echoing what was requested, because a
requested value copied into a served field is exactly the confusion the
plain columns exist to end.

What each harness reports, measured rather than assumed:

* **claude** — its session transcript stamps ``message.model`` and a
  top-level ``effort`` on every assistant row, and states no window at
  all. The window comes from the one surface that does state it, the
  status line JSON, recorded per session by
  :mod:`yoke_harness.claude_status_line`; a session whose status line has
  not run yet reports its model with the window still unattested.
* **codex** — its rollout carries ``turn_context`` (model and effort) and
  a declared ``model_context_window``, the one served window any supported
  harness states outright.
* **cursor** — its per-conversation store names the served variant, and
  because Cursor encodes effort in the variant name that single string
  reports both. It persists no window.

Facts are per-turn, not per-session: a mid-session model or effort switch
shows up as a later value, so each reader takes the newest one it finds.
Newest is also all that is read: Claude's reader takes a bounded window
off the end of its transcript, and Codex's resumes from the same
per-artifact progress record usage folding uses, so a switch stays
visible without re-parsing a session's whole history on every event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_contracts.session_model_facts import (
    SessionModelFacts,
    effort_suffix_of,
    normalize_context_window_tokens,
    normalize_reasoning_effort,
)
from yoke_harness.artifact_scan import scan_rows, tail_rows_newest_first
from yoke_harness.artifact_watermark import (
    MODEL_KIND,
    ArtifactWatermark,
    fold_is_behind,
    load_watermark,
    save_watermark,
    stored_totals,
    watermark_lock,
)


#: Records scanned back from the end for the newest turn. A session long
#: enough to exceed this has its recent turns well inside the window, and
#: the cap is what keeps the read cheap enough to run on a hook event —
#: read from the end of the file, so a session's history costs nothing.
TRANSCRIPT_SCAN_LINES = 500


def attest_served_facts(
    executor: str,
    payload: Mapping[str, Any],
    *,
    transcript_path: str = "",
) -> SessionModelFacts:
    """Return the served facts this session's own artifact proves."""
    from yoke_harness.hooks.identity_runtime import is_claude, is_codex, is_cursor

    try:
        if is_cursor(executor):
            return _cursor_facts(payload)
        if is_codex(executor):
            return _codex_facts(payload)
        if is_claude(executor):
            return _claude_facts(payload, transcript_path)
    except Exception:  # noqa: BLE001 — an unreadable source attests nothing
        return SessionModelFacts()
    return SessionModelFacts()


def _claude_facts(
    payload: Mapping[str, Any], transcript_path: str
) -> SessionModelFacts:
    """Fold Claude's two artifacts into one reading.

    The model and effort come from the transcript, the window from the
    status line recording, and either may be present without the other:
    they are written by different processes at different moments, so each
    is reported the moment it exists rather than waiting for its partner.
    """
    from yoke_harness.claude_status_line import recorded_context_window

    window = recorded_context_window(_text(payload.get("session_id")))
    path = transcript_path or _text(payload.get("transcript_path"))
    if not path or not Path(path).is_file():
        return SessionModelFacts(context_window_tokens=window)
    for row in tail_rows_newest_first(Path(path), max_rows=TRANSCRIPT_SCAN_LINES):
        if row.get("type") != "assistant":
            continue
        message = row.get("message")
        model = _served_model(
            message.get("model") if isinstance(message, dict) else None
        )
        if model is None:
            continue
        return SessionModelFacts(
            model=model,
            reasoning_effort=normalize_reasoning_effort(row.get("effort")),
            context_window_tokens=window,
        )
    return SessionModelFacts(context_window_tokens=window)


def served_facts_catching_up(executor: str, payload: Mapping[str, Any]) -> bool:
    """True when this session's served facts are mid-fold and behind.

    A caller that has already shipped a model stops resolving, which is
    what keeps a settled session cheap. That has to yield while a fold is
    knowingly behind: the newest statement is the served fact, so a
    session whose rollout is still being caught up may have shipped an
    older one, and only continued resolving reaches the current answer.
    Harnesses whose model reads are current by construction — a bounded
    tail, a conversation store — are never behind.
    """
    try:
        from yoke_harness.hooks.identity_runtime import is_codex

        if not is_codex(executor):
            return False
        return fold_is_behind(_codex_thread_id(payload), kind=MODEL_KIND)
    except Exception:  # noqa: BLE001 — an unreadable record blocks nothing
        return False


def _codex_thread_id(payload: Mapping[str, Any]) -> str:
    from yoke_harness.hooks.identity_runtime import resolve_session_id

    return _text(payload.get("thread_id")) or resolve_session_id(
        json.dumps(dict(payload))
    )


def _codex_facts(payload: Mapping[str, Any]) -> SessionModelFacts:
    from yoke_harness.hooks.identity_codex_runtime import codex_transcript_candidates

    thread_id = _codex_thread_id(payload)
    if not thread_id:
        return SessionModelFacts()
    for path in codex_transcript_candidates(thread_id):
        facts = _codex_rollout_facts(path, thread_id)
        if facts.attested():
            return facts
    return SessionModelFacts()


def _codex_rollout_facts(path: Path, thread_id: str) -> SessionModelFacts:
    """Fold one rollout into its last-stated model, effort, and window.

    The three facts arrive on different row types and at different points
    in the run, so each newest statement wins — a turn that changed the
    model does not blank the window the run declared once at startup.
    Keeping those three in a per-artifact progress record is what makes
    that affordable: each event folds only what the rollout gained, and
    the startup window survives in the record rather than by rereading
    the beginning of the file. A reader that arrives while another is
    folding answers from the record instead of scanning the same bytes.
    """
    with watermark_lock(thread_id, kind=MODEL_KIND) as folding:
        mark = load_watermark(thread_id, path, kind=MODEL_KIND)
        held = dict(stored_totals(mark))
        if not folding:
            return _facts_from_record(held, mark.caught_up)

        def fold(row: Mapping[str, Any]) -> None:
            block = row.get("payload")
            if not isinstance(block, dict):
                return
            if row.get("type") == "turn_context":
                held["model"] = _served_model(block.get("model")) or held.get("model")
                held["effort"] = normalize_reasoning_effort(
                    block.get("effort")
                ) or held.get("effort")
            held["window"] = _codex_window(block) or held.get("window")

        scan = scan_rows(path, mark.offset, fold)
        save_watermark(
            thread_id,
            path,
            ArtifactWatermark(
                offset=scan.offset,
                totals=held,
                truncated=mark.truncated,
                oversized=mark.oversized or scan.oversized,
                caught_up=scan.caught_up,
            ),
            kind=MODEL_KIND,
        )
    return _facts_from_record(held, scan.caught_up)


def _facts_from_record(held: Mapping[str, Any], caught_up: bool) -> SessionModelFacts:
    """Present the folded record, but only once the fold reached the end.

    A served fact is the newest statement in the rollout, so a fold that
    stopped at its byte bound is holding a historical one. Attesting it
    would be worse than attesting nothing: the caller settles a session
    the moment its model lands, and a stale model that settles is the
    model that session reports for the rest of its life. Unattested facts
    make the next event resume the fold instead.
    """
    if not caught_up:
        return SessionModelFacts()
    return SessionModelFacts(
        model=_served_model(held.get("model")),
        reasoning_effort=normalize_reasoning_effort(held.get("effort")),
        context_window_tokens=normalize_context_window_tokens(held.get("window")),
    )


def _codex_window(block: Mapping[str, Any]) -> Optional[int]:
    """Read the declared served window from either row that states it."""
    direct = normalize_context_window_tokens(block.get("model_context_window"))
    if direct is not None:
        return direct
    info = block.get("info")
    if isinstance(info, dict):
        return normalize_context_window_tokens(info.get("model_context_window"))
    return None


def _cursor_facts(payload: Mapping[str, Any]) -> SessionModelFacts:
    from yoke_harness.cursor_executed_model import executed_model_for_payload

    model = _served_model(executed_model_for_payload(payload))
    if model is None:
        return SessionModelFacts()
    return SessionModelFacts(model=model, reasoning_effort=effort_suffix_of(model))


def _served_model(value: object) -> Optional[str]:
    """Return a real served id, or ``None`` for a placeholder or a blank."""
    from yoke_harness.hooks.identity_runtime import _is_placeholder_model

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or _is_placeholder_model(text):
        return None
    return text


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "TRANSCRIPT_SCAN_LINES",
    "attest_served_facts",
    "served_facts_catching_up",
]
