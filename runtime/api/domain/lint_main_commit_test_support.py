# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import io

import json

import unittest

from contextlib import redirect_stdout

from unittest import mock

from yoke_contracts.hook_runner.main_commit import (
    CLIENT_GIT_COMMIT_FACTS_KEY,
    CLIENT_GIT_COMMIT_FACTS_SCHEMA,
)

from yoke_contracts.hook_runner.shell_parse import parse_shell

from yoke_core.domain import lint_main_commit

from yoke_core.hooks.guard_denial_record import guard_audit_outcome

from yoke_core.hooks.types import HookContext, Next, Outcome

TEST_ITEM_REF = "YOK-42"


def git_facts(branch: str | None, staged: list[str]) -> dict:
    """The client's report of its checkout branch and effective staged set."""
    return {
        CLIENT_GIT_COMMIT_FACTS_KEY: {
            "schema": CLIENT_GIT_COMMIT_FACTS_SCHEMA,
            "is_git_commit": True,
            "repo_cwd": "/client/checkout",
            "branch": branch,
            "staged_paths": staged,
            "staged_probe_ok": True,
            "status_probe_ok": True,
        }
    }


def _evaluate_payload(payload: dict):
    """Run the policy on *payload* with its one shared shell parse."""
    shell = parse_shell(lint_main_commit._extract_command(payload))
    return lint_main_commit.evaluate_payload(payload, shell)


def _payload(command: str, facts: dict | None = None) -> dict:
    return {
        **(facts or {}),
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
