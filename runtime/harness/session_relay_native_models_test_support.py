# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

from runtime.harness.session_relay_clock_test_support import at

from yoke_contracts.session_control.native_model_parsers import (
    codex_next_cursor,
    cursor_token_effort,
    parse_codex_models,
    parse_cursor_models,
)

from yoke_contracts.session_control.native_models import (
    MAX_MODELS_PER_SURFACE,
    NATIVE_MODEL_SURFACES,
    NO_ADAPTER_REASON,
    TRUNCATED_REASON,
    available_models,
    empty_reading,
    models_reading,
    native_model,
    sanitize_native_models,
    stale_reading,
)

from yoke_harness import session_relay_native_models as observer

CURSOR_OUTPUT = """Available models

auto - Auto (default)
cursor-grok-4.6-low - Cursor Grok 4.6 Low
cursor-grok-4.6-xhigh - Cursor Grok 4.6 Extra High
cursor-grok-4.6-xhigh-fast - Cursor Grok 4.6 Extra High Fast
"""
