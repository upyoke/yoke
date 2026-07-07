"""Legacy argv-style event emitter helper.

Accepts the same positional argv shape older Yoke Python modules used so
they can port to the native emitter with a one-line delegate instead of
restructuring each call site. Today this is consumed only by
``yoke_core.domain.deploy_pipeline_reporting``'s ``_emit_event`` shim.

Design contract (matches the native emitter):
- Event emission is **non-fatal**.  Failures are logged at DEBUG and
  swallowed — they must never crash callers.
- Returns an :class:`~yoke_core.domain.events.EmitResult` whose ``ok``
  flag distinguishes success from failure / malformed args, or ``None``
  when an exception escapes the parser.
- Unknown ``--flag`` values are ignored so the helper is forgiving.

``yoke_core.domain.events`` re-exports ``emit_event_argv`` so callers that
import it from ``yoke_core.domain.events`` continue to work.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from .events import EmitResult, emit_event

logger = logging.getLogger(__name__)


_ARGV_FIELD_TO_KWARG = {
    "kind": "event_kind",
    "type": "event_type",
    "source-type": "source_type",
    "session-id": "session_id",
    "user-id": "user_id",
    "org-id": "org_id",
    "environment": "environment",
    "request-id": "request_id",
    "severity": "severity",
    "outcome": "outcome",
    "project": "project",
    "item-id": "item_id",
    "task-num": "task_num",
    "agent": "agent",
    "tool-name": "tool_name",
    "duration-ms": "duration_ms",
    "trace-id": "trace_id",
    "parent-id": "parent_id",
    "anomaly-flags": "anomaly_flags",
    "tool-use-id": "tool_use_id",
    "turn-id": "turn_id",
    "hook-event-name": "hook_event_name",
}


def emit_event_argv(argv: list) -> Optional[EmitResult]:
    """Emit an event using legacy ``--flag value`` argv.

    Parses the subset of legacy flags Yoke Python modules actually used,
    then delegates to :func:`emit_event`. Unknown flags are ignored so this
    helper is forgiving for callers passing extras.

    Returns the :class:`EmitResult` from the underlying emitter, or ``None``
    when an exception escapes the parser. Non-fatal — never raises.
    """
    try:
        parsed: Dict[str, str] = {}
        i = 0
        while i < len(argv):
            flag = argv[i]
            if isinstance(flag, str) and flag.startswith("--") and i + 1 < len(argv):
                parsed[flag[2:]] = str(argv[i + 1])
                i += 2
            else:
                i += 1

        name = parsed.pop("name", "")
        if not name:
            return None

        context_raw = parsed.pop("context", "")
        context: Optional[Dict[str, Any]] = None
        if context_raw:
            try:
                context = json.loads(context_raw)
                if not isinstance(context, dict):
                    context = {"value": context}
            except json.JSONDecodeError:
                context = {"raw": context_raw}

        kwargs: Dict[str, Any] = {
            "event_kind": "lifecycle",
            "event_type": "generic",
            "source_type": "backend",
            "severity": "INFO",
            "outcome": "completed",
            "project": "yoke",
        }
        for flag, value in parsed.items():
            target = _ARGV_FIELD_TO_KWARG.get(flag)
            if target is None:
                continue
            if target in ("task_num", "duration_ms"):
                try:
                    kwargs[target] = int(value)
                except ValueError:
                    continue
            else:
                kwargs[target] = value
        if context is not None:
            kwargs["context"] = context

        return emit_event(name, **kwargs)
    except Exception as exc:
        logger.debug("emit_event_argv failed: %s", exc)
        return None
