"""``yoke hook evaluate`` local-universe routing."""

from __future__ import annotations

import io
import json
import os
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


def test_local_universe_hook_adopts_the_launched_native(
    monkeypatch,
    tmp_path,
) -> None:
    """A local universe writes the launch handle its own relay reads.

    The handle is the only machine-local record binding a launched session to
    the pid that served it, and both the relay's process-death report and the
    native's captured token totals hang off it. A universe served in-process
    ran a hook entry that never settled the launch projection, so no handle
    was ever written: the session's death went unreported until the stale
    sweep and its measured usage stayed unavailable forever.
    """
    from yoke_harness import session_launch_handles
    from yoke_harness.session_launch_containment import record_supervised_native
    from yoke_core.hooks import local_entry

    launch_id = "3e0cb7c7-2453-427b-afda-c0e23ffeaafe"
    session_id = "edf9a3d4-d4c0-4cab-bcc9-e6e415f9cd3f"
    message_id = "2c0f305a-1ebc-4cf0-9c0c-62f80f94aed3"

    handles = tmp_path / "session-native-handles"
    custody = tmp_path / "custody"
    monkeypatch.setattr(
        session_launch_handles,
        "native_handle_directory",
        lambda: (handles.mkdir(mode=0o700, parents=True, exist_ok=True) or handles),
    )
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.cache_dir",
        lambda *_a, **_k: custody,
    )
    monkeypatch.setenv(
        "YOKE_SESSION_LAUNCH_CONTEXT",
        json.dumps({"launch_id": launch_id, "attestation": "token"}),
    )
    assert record_supervised_native(launch_id, os.getpid())

    delivered = (
        f"=== BEGIN YOKE LAUNCH DELIVERY YOKE_SESSION_LAUNCH:{launch_id}:"
        f"{message_id} ===\n--- begin instructions ---\nwork\n"
        "--- end instructions ---\n"
    )
    monkeypatch.setattr(local_entry, "detect_executor", lambda: "cursor")
    monkeypatch.setattr(local_entry, "record_client_anchor", lambda *_a, **_k: None)
    monkeypatch.setattr(local_entry, "capture_codex_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        local_entry, "ensure_user_lifecycle_hooks_for_executor", lambda *_a: None
    )
    monkeypatch.setattr(local_entry, "relay_identity_payload", lambda *_a, **_k: {})
    monkeypatch.setattr(
        local_entry, "record_model_facts_shipped", lambda *_a, **_k: None
    )
    monkeypatch.setattr(local_entry, "confirmed_served_model", lambda *_a, **_k: None)
    monkeypatch.setattr(local_entry, "resolve_capability", lambda *_a, **_k: None)
    monkeypatch.setattr(
        local_entry, "run_event", lambda *_a, **_k: (delivered, 0)
    )

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert (
            local_entry.evaluate_local_hook(
                "SessionStart",
                json.dumps({"session_id": session_id}),
            )
            == 0
        )

    handle = handles / f"{launch_id}.json"
    assert handle.is_file(), "the launched native was never adopted"
    assert json.loads(handle.read_text())["target_session_id"] == session_id
    assert not (
        custody / "session-launch-supervision" / f"{launch_id}.json"
    ).exists(), "custody outlived the delivery that proved registration"
