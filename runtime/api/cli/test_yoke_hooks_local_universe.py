"""``yoke hook evaluate`` local-universe routing."""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from uuid import UUID

from runtime.api.cli.test_yoke_operations_cli_hooks import (  # noqa: F401
    _FakeResponse,
    https_connection,
    local_subset,
)
from yoke_cli.main import main as cli_main


_RESOLVE = "yoke_cli.transport.https.resolve_https_connection"
_LOCAL = "yoke_cli.commands.adapters.hook_inprocess._evaluate_local_universe_hook"
_ACTIVE = "yoke_cli.commands.adapters.hook_inprocess._active_local_universe"


def test_bound_local_universe_runs_complete_engine_chain(monkeypatch) -> None:
    monkeypatch.setattr(_RESOLVE, lambda: None)
    monkeypatch.setattr(_ACTIVE, lambda: True)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s1"}'))
    local_calls: list[tuple] = []
    monkeypatch.setattr(
        _LOCAL, lambda *args, **kwargs: local_calls.append((args, kwargs)) or 0
    )
    with patch(
        "yoke_harness.hooks.relay.evaluate_hook_event",
        side_effect=AssertionError("bound local universe must use yoke-core"),
    ) as hook_main:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = cli_main(["hook", "evaluate", "PreToolUse"])

    assert rc == 0
    hook_main.assert_not_called()
    assert len(local_calls) == 1
    args, kwargs = local_calls[0]
    assert args[0] == "PreToolUse"
    payload = json.loads(args[1])
    timing_id = payload["yoke_hook_evaluator"].pop("client_timing_id")
    assert str(UUID(timing_id)) == timing_id
    assert payload == {
        "session_id": "s1",
        "yoke_hook_evaluator": {
            "evaluator": "inprocess",
            "warm_duration_ms": 0,
        },
    }
    assert kwargs == {"extra_context": ""}


def test_unbound_machine_retains_client_subset(monkeypatch) -> None:
    monkeypatch.setattr(_RESOLVE, lambda: None)
    monkeypatch.setattr(_ACTIVE, lambda: False)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s1"}'))
    with patch(
        "yoke_harness.hooks.relay.evaluate_hook_event",
        return_value=0,
    ) as hook_main:
        assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0
    hook_main.assert_called_once()
    args, kwargs = hook_main.call_args
    assert args == ("PreToolUse",)
    assert json.loads(kwargs["stdin_data"])["session_id"] == "s1"
    assert kwargs["extra_context"] == ""


def test_https_relay_skips_local_engine(
    monkeypatch,
    https_connection,  # noqa: F811
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('{"session_id": "s1", "tool_name": "Bash"}'),
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.detect_executor",
        lambda: "claude-code",
    )
    monkeypatch.setattr(
        "yoke_harness.hooks.relay.record_session_anchor",
        lambda *_a, **_k: None,
    )
    driven: list = []
    monkeypatch.setattr(_LOCAL, lambda *a, **k: driven.append((a, k)))
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: _FakeResponse(
            json.dumps(
                {
                    "hook_schema": 1,
                    "stdout": "",
                    "exit_code": 0,
                    "wait_ms": 1,
                    "degraded": [],
                    "outcome": "completed",
                }
            ).encode("utf-8")
        ),
    )
    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0
    assert driven == []


def test_missing_local_engine_is_loud(monkeypatch, capsys) -> None:
    from yoke_cli.commands.adapters import hook_inprocess as hooks_mod

    def _missing(_name):
        raise ModuleNotFoundError("No module named 'yoke_core.hooks.local_entry'")

    monkeypatch.setattr("importlib.import_module", _missing)
    rc = hooks_mod._evaluate_local_universe_hook(
        "PreToolUse",
        '{"session_id": "s1"}',
        extra_context="",
    )
    assert rc == 1
    assert "YOKE_LOCAL_HOOK_ENGINE_MISSING" in capsys.readouterr().err
