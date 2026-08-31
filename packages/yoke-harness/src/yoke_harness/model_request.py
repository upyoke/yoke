"""What a harness session was asked to run, per harness.

The ask and the served truth are recorded in different columns, and this
module owns the ask half. Each harness offers a different set of request
channels, and only the ones that genuinely exist are read:

* **claude** — the model rides ``--model`` (or ``YOKE_MODEL`` from a Yoke
  launch), effort rides ``CLAUDE_CODE_EFFORT_LEVEL``, and the context tier
  is asked for either as the ``[1m]`` selector on the model string or as an
  explicit ``CLAUDE_CODE_MAX_CONTEXT_TOKENS`` cap.
* **cursor** — one flat variant name carries the model and the effort
  together (``cursor-grok-4.6-xhigh``), so the effort is read out of the
  requested name. Cursor exposes no separate context-window request.
* **codex** — the model is requestable per invocation, but effort and
  context window are configuration a Yoke launch does not carry and a hook
  process cannot attribute to this session's ask. Both stay ``None``: a
  designed gap, not a value to invent. Codex is also the one harness that
  *declares* its served window, so the fact is recoverable on the truth
  side rather than guessed on the request side.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from yoke_contracts.session_model_facts import (
    SessionModelFacts,
    effort_suffix_of,
    normalize_context_window_tokens,
    normalize_reasoning_effort,
    requested_context_window_of,
)


CLAUDE_EFFORT_ENV = "CLAUDE_CODE_EFFORT_LEVEL"
CLAUDE_MAX_CONTEXT_ENV = "CLAUDE_CODE_MAX_CONTEXT_TOKENS"


def requested_facts(
    executor: str,
    payload: Mapping[str, Any] | None = None,
) -> SessionModelFacts:
    """Return the request this session carries, as far as it is stated."""
    from yoke_harness.hooks.identity_runtime import (
        _is_placeholder_model,
        detect_requested_model,
        is_claude,
        is_cursor,
    )

    payload = payload or {}
    wire = payload.get("requested_model")
    model = wire.strip() if isinstance(wire, str) and wire.strip() else ""
    if not model or _is_placeholder_model(model):
        model = detect_requested_model(executor)
    if _is_placeholder_model(model):
        return SessionModelFacts()
    if is_cursor(executor):
        return SessionModelFacts(
            requested_model=model,
            requested_reasoning_effort=effort_suffix_of(model),
        )
    if is_claude(executor):
        return SessionModelFacts(
            requested_model=model,
            requested_reasoning_effort=normalize_reasoning_effort(
                os.environ.get(CLAUDE_EFFORT_ENV)
            ),
            requested_context_window_tokens=_claude_requested_window(model),
        )
    return SessionModelFacts(requested_model=model)


def _claude_requested_window(model: str) -> Optional[int]:
    """An explicit cap outranks the tier selector that implies one."""
    explicit = normalize_context_window_tokens(os.environ.get(CLAUDE_MAX_CONTEXT_ENV))
    return explicit if explicit is not None else requested_context_window_of(model)


__all__ = ["CLAUDE_EFFORT_ENV", "CLAUDE_MAX_CONTEXT_ENV", "requested_facts"]
