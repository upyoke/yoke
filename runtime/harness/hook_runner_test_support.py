# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import importlib

import os

import subprocess

import sys

import time

from pathlib import Path

from typing import Any

import pytest

from yoke_core.hooks import runner as runner_module

from yoke_core.hooks import telemetry as telemetry_module

from yoke_core.hooks import subprocess_policy

from yoke_core.hooks.adapter_capability import AdapterCapability

from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


def _silence_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop runner telemetry emissions so smoke tests don't touch the events table."""
    for name in (
        "emit_hook_execution_failed",
        "emit_hook_guardrail_evaluated",
        "emit_hook_dispatch_telemetry",
    ):
        monkeypatch.setattr(telemetry_module, name, lambda **k: None)


def _patch_typed_modules(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, Any],
) -> None:
    """Substitute ``importlib.import_module`` for a closed set of dotted ids."""
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        if name in mapping:
            return mapping[name]
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
