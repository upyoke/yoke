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

from yoke_core.hooks.adapter_capability import AdapterCapability

from yoke_core.hooks.decision_render import render_claude_decision

from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


def _capability(
    monkeypatch: pytest.MonkeyPatch,
    chain: list[str],
    *,
    subprocess_modules: frozenset[str] = frozenset(),
) -> AdapterCapability:
    """Build a capability + monkeypatch chain_registry to return ``chain``."""
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: list(chain))
    return AdapterCapability(
        family="claude",
        payload_parser=lambda raw: {},
        decision_renderer=render_claude_decision,
        subprocess_modules=subprocess_modules,
    )


def _silence_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "emit_hook_execution_failed",
        "emit_hook_guardrail_evaluated",
        "emit_hook_dispatch_telemetry",
    ):
        monkeypatch.setattr(telemetry_module, name, lambda **k: None)


_SUBPROC_RUN = "yoke_core.hooks.subprocess_policy.subprocess.run"


def _patch_typed_modules(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, Any],
) -> None:
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        if name in mapping:
            return mapping[name]
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
