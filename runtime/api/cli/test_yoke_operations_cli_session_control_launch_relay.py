"""Focused CLI contracts for session launch and machine-relay operations."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from yoke_cli.commands.adapters import session_control_launches as launches
from yoke_cli.commands.adapters import session_control_relay as relay
from yoke_cli.commands.registry_session_control import (
    SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY,
    SESSION_CONTROL_TOOL_SHAPED_SUBCOMMANDS,
)


def test_sessions_create_preview_and_create_use_registered_functions(
    monkeypatch,
) -> None:
    calls = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(launches, "dispatch_and_emit", _dispatch)
    monkeypatch.setattr(sys, "stdin", io.StringIO("private instructions"))
    base = [
        "--project",
        "yoke",
        "--surface",
        "codex-desktop",
        "--machine",
        "machine-1",
        "--model",
        "gpt-5.6",
    ]
    assert launches.sessions_create([*base, "--preview"]) == 0
    assert (
        launches.sessions_create(
            [
                *base,
                "--stdin",
                "--idempotency-key",
                "launch-1",
                "--presentation",
                "focused",
            ]
        )
        == 0
    )

    assert calls[0]["function_id"] == "session_control.launch.preview"
    assert calls[0]["payload"] == {
        "project": "yoke",
        "executor_surface": "codex-desktop",
        "machine_id": "machine-1",
        "model": "gpt-5.6",
        "allow_surface_fallback": False,
    }
    assert calls[1]["function_id"] == "session_control.launch.create"
    assert calls[1]["payload"] == {
        **calls[0]["payload"],
        "instructions": "private instructions",
        "idempotency_key": "launch-1",
        "presentation": "focused",
    }
    assert calls[1]["sensitive_values"] == ("private instructions",)
    assert SESSION_CONTROL_SUBCOMMAND_ALIAS_REGISTRY[("sessions", "create")][0] == (
        "session_control.launch.create"
    )


def test_launch_lifecycle_adapters_build_typed_payloads(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        launches,
        "dispatch_and_emit",
        lambda **kwargs: calls.append(kwargs) or 0,
    )
    assert launches.session_launch_get(["launch-1"]) == 0
    assert (
        launches.session_launch_list(
            [
                "--project",
                "yoke",
                "--state",
                "outcome_unknown",
                "--limit",
                "4",
            ]
        )
        == 0
    )
    assert launches.session_launch_cancel(["launch-1"]) == 0
    assert launches.session_launch_retry(["launch-1"]) == 0
    assert (
        launches.session_launch_reconcile(
            [
                "launch-1",
                "--observed-native-id",
                "native-1",
            ]
        )
        == 0
    )

    assert [call["function_id"] for call in calls] == [
        "session_control.launch.get",
        "session_control.launch.list",
        "session_control.launch.cancel",
        "session_control.launch.retry",
        "session_control.launch.reconcile",
    ]
    assert calls[1]["payload"] == {
        "project": "yoke",
        "state": "outcome_unknown",
        "limit": 4,
    }
    assert calls[-1]["payload"] == {
        "launch_id": "launch-1",
        "observed_native_id": "native-1",
    }


def test_relay_lifecycle_is_local_and_structured(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        relay,
        "_plist_operation",
        lambda action: SimpleNamespace(
            supported=True,
            plist_present=action != "uninstall",
            plist_current=action != "uninstall",
            loaded=action != "uninstall",
            plist_path=Path("/tmp/com.upyoke.relay.plist"),
        ),
    )
    assert relay.relay_install(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "loaded": True,
        "plist_current": True,
        "plist_path": "/tmp/com.upyoke.relay.plist",
        "plist_present": True,
        "supported": True,
    }


@dataclass(frozen=True)
class _Outcome:
    state: str
    next_poll_seconds: int
    job_kind: str | None = None
    job_id: str | None = None
    result_code: str | None = None
    error_code: str | None = None


def test_relay_serve_once_calls_the_machine_helper(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        relay,
        "_serve_once",
        lambda: _Outcome("reported", 60, "launch", "launch-1", "native_created"),
    )
    assert relay.relay_serve_once(["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "error_code": None,
        "job_id": "launch-1",
        "job_kind": "launch",
        "next_poll_seconds": 60,
        "result_code": "native_created",
        "state": "reported",
    }
    assert set(SESSION_CONTROL_TOOL_SHAPED_SUBCOMMANDS) == {
        ("relay", "install"),
        ("relay", "uninstall"),
        ("relay", "status"),
        ("relay", "serve-once"),
    }
