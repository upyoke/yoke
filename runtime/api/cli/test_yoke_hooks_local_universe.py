"""``yoke hook evaluate`` local-universe routing.

On a machine with no https connection, the adapter runs the client-local
lint subset for the verdict (unchanged) and then drives the in-process
session lifecycle against a bound local universe. The relay/https path must
never drive that lifecycle — every current session depends on it unchanged.
Shares the wire fixtures of ``test_yoke_operations_cli_hooks.py``.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from runtime.api.cli.test_yoke_operations_cli_hooks import (  # noqa: F401
    _FakeResponse,
    https_connection,
    local_subset,
)
from yoke_cli.main import main as cli_main


_RESOLVE = "yoke_cli.transport.https.resolve_https_connection"
_DRIVE = "yoke_cli.commands.adapters.hooks._drive_local_universe_lifecycle"


def test_no_https_runs_lint_subset_then_drives_lifecycle(monkeypatch) -> None:
    # No https: the lint subset runs on the shared stdin (owns the verdict),
    # then the local-universe lifecycle is driven from the same payload.
    monkeypatch.setattr(_RESOLVE, lambda: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s1"}'))
    lifecycle_calls: list = []
    monkeypatch.setattr(
        _DRIVE, lambda event, stdin_data: lifecycle_calls.append((event, stdin_data)),
    )
    with patch(
        "yoke_harness.hooks.relay.evaluate_hook_event",
        return_value=0,
    ) as hook_main:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_main(["hook", "evaluate", "PreToolUse"])

    assert rc == 0
    assert hook_main.call_count == 1
    assert hook_main.call_args.args == ("PreToolUse",)
    assert hook_main.call_args.kwargs == {"stdin_data": '{"session_id": "s1"}'}
    assert lifecycle_calls == [("PreToolUse", '{"session_id": "s1"}')]


def test_https_relay_skips_local_universe_lifecycle(
    monkeypatch, https_connection,  # noqa: F811
) -> None:
    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO('{"session_id": "s1", "tool_name": "Bash"}'),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor", lambda: "claude-code",
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor", lambda *_a, **_k: None,
    )
    driven: list = []
    monkeypatch.setattr(_DRIVE, lambda *a: driven.append(a))
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(json.dumps({
            "hook_schema": 1, "stdout": "", "exit_code": 0,
            "wait_ms": 1, "degraded": [], "outcome": "completed",
        }).encode("utf-8")),
    )
    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0
    assert driven == []


def test_drive_helper_is_fail_open_on_orchestrator_error(monkeypatch) -> None:
    # A lifecycle failure must never propagate into the hook decision.
    from yoke_cli.commands.adapters import hooks as hooks_mod

    def _boom(*_a, **_k):
        raise RuntimeError("lifecycle exploded")

    monkeypatch.setattr(
        "runtime.harness.hook_runner.local_universe_lifecycle."
        "run_local_universe_session_lifecycle",
        _boom,
    )
    # Must not raise.
    hooks_mod._drive_local_universe_lifecycle("PreToolUse", '{"session_id": "s1"}')
