# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import unittest

from unittest import mock

from yoke_core.domain import lint_raw_pytest_full_suite as lint

from yoke_core.hooks.guard_denial_record import guard_audit_outcome

from yoke_core.hooks.types import Next, Outcome


def _payload(command: str, **extra) -> dict:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    payload.update(extra)
    return payload


def _eval(command: str):
    return lint.evaluate_payload(_payload(command))


def _anchor_sweep() -> str:
    return "uv run --frozen python3 -m pytest " + " ".join(
        f"{anchor}/" for anchor in lint.full_sweep_anchors()
    )
