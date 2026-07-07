"""Trace/span context adapter for Yoke semantic events."""

from __future__ import annotations

from typing import Dict


def current_trace_context() -> Dict[str, str]:
    try:
        from yoke_core.api.observability import trace_context
    except Exception:
        return {}
    try:
        return trace_context()
    except Exception:
        return {}
