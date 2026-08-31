"""Compatibility surface for observe-tool event processing.

The implementation lives in responsibility-named siblings. This module keeps
``yoke_core.domain.observe`` import and ``python3 -m`` compatibility intact.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import observe_cli as _observe_cli
from yoke_core.domain import observe_codex_transcript as _observe_codex_transcript
from yoke_core.domain.observe_anomaly import detect_anomalies
from yoke_core.domain.observe_cli import _resolve_db_fallback
from yoke_core.domain.observe_constants import BUSY_TIMEOUT_MS
from yoke_core.domain.observe_codex_transcript import _TRANSCRIPT_TAIL_BYTES
from yoke_core.domain.observe_event_emission import build_envelope, insert_event
from yoke_core.domain.observe_db_reads import (
    compute_tool_call_duration as _compute_duration,
)
from yoke_core.domain.observe_normalization import _resolve_main_session_attribution
from yoke_core.domain.observe_parsing import (
    EventRecord,
    _extract_response_text,
    parse_hook_event as _parse_hook_event,
)
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

__all__ = [
    "BUSY_TIMEOUT_MS",
    "EventRecord",
    "parse_hook_event",
    "detect_anomalies",
    "build_envelope",
    "insert_event",
    "evaluate",
    "main",
    "_compute_duration",
    "_extract_response_text",
    "_resolve_main_session_attribution",
    "_TRANSCRIPT_TAIL_BYTES",
]


def parse_hook_event(*args: Any, **kwargs: Any) -> Optional[EventRecord]:
    """Parse hook payloads while preserving shim-level transcript monkeypatches."""
    _observe_codex_transcript._TRANSCRIPT_TAIL_BYTES = _TRANSCRIPT_TAIL_BYTES
    return _parse_hook_event(*args, **kwargs)


def evaluate(record: HookContext) -> HookDecision:
    """Typed PostToolUse telemetry. Always NOOP so the chain cannot block."""
    try:
        payload = record.payload if isinstance(record.payload, dict) else {}
        if payload:
            tool_use_id = payload.get("tool_use_id")
            _observe_cli.record_hook_event(
                payload,
                session_id=record.session_id or "",
                item_id=str(record.item_id) if record.item_id is not None else None,
                hook_event=record.event_name,
                tool_use_id=str(tool_use_id) if tool_use_id else None,
                project_dir=record.cwd,
            )
    except Exception:
        pass
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def main() -> None:
    """CLI entry point preserving shim-level fallback monkeypatching."""
    _observe_cli.main(db_fallback_resolver=_resolve_db_fallback)


if __name__ == "__main__":
    main()
