"""Entrypoint ownership tests for Fleet live acceptance."""

from __future__ import annotations

import json

from runtime.api.tools import session_control_live_acceptance as acceptance
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceMatrix,
)


def test_subagent_refuses_before_loading_matrix_or_calling_cli(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: True)
    monkeypatch.setattr(
        acceptance,
        "load_matrix",
        lambda _path: (_ for _ in ()).throw(AssertionError("matrix loaded")),
    )
    monkeypatch.setattr(
        acceptance,
        "YokeCliClient",
        lambda: (_ for _ in ()).throw(AssertionError("CLI constructed")),
    )

    code = acceptance.main(["--matrix", "matrix.json", "--run-id", "release-1"])

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["status"] == "refused"
    assert report["failure_code"] == "top_level_session_required"


def test_top_level_entrypoint_emits_machine_readable_report(
    monkeypatch, capsys
) -> None:
    matrix = AcceptanceMatrix(
        "yoke",
        (AcceptanceCell("codex-desktop", "26.814.41407", "create"),),
    )
    captured = {}

    class _Driver:
        def __init__(self, client) -> None:
            captured["client"] = client

        def run(self, supplied, **kwargs):
            captured.update(matrix=supplied, kwargs=kwargs)
            return {
                "schema": 1,
                "kind": "fleet_session_control_live_acceptance",
                "status": "passed",
                "cells": [],
            }

    sentinel = object()
    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: False)
    monkeypatch.setattr(acceptance, "_caller_session_id", lambda: "main-session")
    monkeypatch.setattr(acceptance, "load_matrix", lambda _path: matrix)
    monkeypatch.setattr(acceptance, "YokeCliClient", lambda: sentinel)
    monkeypatch.setattr(acceptance, "LiveAcceptanceDriver", _Driver)

    code = acceptance.main(
        [
            "--matrix",
            "matrix.json",
            "--run-id",
            "release-2",
            "--timeout-seconds",
            "12",
            "--poll-seconds",
            "2",
            "--unsupported-observation-seconds",
            "4",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["status"] == "passed"
    assert captured["client"] is sentinel
    assert captured["matrix"] is matrix
    assert captured["kwargs"] == {
        "run_id": "release-2",
        "caller_session_id": "main-session",
        "timeout_seconds": 12.0,
        "poll_seconds": 2.0,
        "unsupported_observation_seconds": 4.0,
    }


def test_entrypoint_refuses_invalid_windows_without_cli(monkeypatch, capsys) -> None:
    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        acceptance,
        "YokeCliClient",
        lambda: (_ for _ in ()).throw(AssertionError("CLI constructed")),
    )

    code = acceptance.main(
        [
            "--matrix",
            "matrix.json",
            "--run-id",
            "release-3",
            "--poll-seconds",
            "0",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["failure_code"] == "poll_window_invalid"


def test_execution_guard_recognizes_a_codex_child(monkeypatch) -> None:
    for key in (
        "YOKE_HOOK_AGENT_TYPE",
        "CURSOR_CONVERSATION_ID",
        "CURSOR_TRANSCRIPT_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CODEX_SESSION_ID", "parent-session")
    monkeypatch.setenv("CODEX_THREAD_ID", "child-thread")

    assert acceptance._is_subagent_execution() is True
