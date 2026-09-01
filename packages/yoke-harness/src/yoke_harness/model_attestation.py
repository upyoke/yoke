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


#: Transcript tail scanned for the newest turn. A session long enough to
#: exceed this has its recent turns well inside the window, and the cap is
#: what keeps the read cheap enough to run on a hook event.
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
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in reversed(raw.splitlines()[-TRANSCRIPT_SCAN_LINES:]):
        row = _row(line)
        if row is None or row.get("type") != "assistant":
            continue
        message = row.get("message")
        model = _served_model(message.get("model") if isinstance(message, dict) else None)
        if model is None:
            continue
        return SessionModelFacts(
            model=model,
            reasoning_effort=normalize_reasoning_effort(row.get("effort")),
            context_window_tokens=window,
        )
    return SessionModelFacts(context_window_tokens=window)


def _codex_facts(payload: Mapping[str, Any]) -> SessionModelFacts:
    from yoke_harness.hooks.identity_codex_runtime import codex_transcript_candidates
    from yoke_harness.hooks.identity_runtime import resolve_session_id

    thread_id = _text(payload.get("thread_id")) or resolve_session_id(
        json.dumps(dict(payload))
    )
    if not thread_id:
        return SessionModelFacts()
    for path in codex_transcript_candidates(thread_id):
        facts = _codex_rollout_facts(path)
        if facts.attested():
            return facts
    return SessionModelFacts()


def _codex_rollout_facts(path: Path) -> SessionModelFacts:
    """Fold one rollout into its last-stated model, effort, and window.

    The three facts arrive on different row types and at different points
    in the run, so the whole file is folded and the newest statement of
    each wins — a turn that changed the model does not blank the window
    the run declared once at startup.
    """
    model: Optional[str] = None
    effort: Optional[str] = None
    window: Optional[int] = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            row = _row(line)
            if row is None:
                continue
            block = row.get("payload")
            if not isinstance(block, dict):
                continue
            if row.get("type") == "turn_context":
                model = _served_model(block.get("model")) or model
                effort = normalize_reasoning_effort(block.get("effort")) or effort
            window = _codex_window(block) or window
    return SessionModelFacts(
        model=model, reasoning_effort=effort, context_window_tokens=window
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


def _row(line: str) -> Optional[dict]:
    if not line.strip():
        return None
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["TRANSCRIPT_SCAN_LINES", "attest_served_facts"]
