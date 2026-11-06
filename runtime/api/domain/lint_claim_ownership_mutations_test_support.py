# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json

import unittest

from yoke_core.domain import lint_claim_ownership_mutations as lint

from yoke_core.hooks.guard_denial_record import guard_audit_outcome

from yoke_core.hooks.types import HookContext, Next, Outcome

_AMBIENT = "sess-self"


def _payload(command: str, session_id: str = _AMBIENT) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session_id,
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
