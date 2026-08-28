"""Entrypoint ownership tests for Fleet live acceptance."""

from __future__ import annotations

import json

from runtime.api.tools import session_control_live_acceptance as acceptance
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceMatrix,
)


RELEASE_SHA = "a" * 40
SERVER_BUILD = RELEASE_SHA


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

    code = acceptance.main(
        [
            "--matrix",
            "matrix.json",
            "--run-id",
            "release-1",
            "--release-sha",
            RELEASE_SHA,
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["status"] == "refused"
    assert report["failure_code"] == "top_level_session_required"


def test_top_level_entrypoint_emits_machine_readable_report(
    monkeypatch, capsys
) -> None:
    matrix = AcceptanceMatrix(
        "yoke",
        (AcceptanceCell("codex-cli", "0.148.0-alpha.15", "create"),),
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

    class _Client:
        def deployed_release(self):
            return {
                "server_build": SERVER_BUILD,
                "engine_version": "0.1.1+launch.999",
            }

    sentinel = _Client()
    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: False)
    monkeypatch.setattr(acceptance, "_caller_session_id", lambda: "main-session")
    monkeypatch.setattr(
        acceptance, "_require_final_acceptance_environment", lambda: "prod"
    )
    monkeypatch.setattr(acceptance, "load_matrix", lambda _path: matrix)
    monkeypatch.setattr(
        acceptance,
        "QualificationCoordinator",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("default acceptance must not open qualification")
        ),
    )
    monkeypatch.setattr(
        acceptance,
        "YokeCliClient",
        lambda *, explicit_env: sentinel if explicit_env == "prod" else None,
    )
    monkeypatch.setattr(acceptance, "LiveAcceptanceDriver", _Driver)

    code = acceptance.main(
        [
            "--matrix",
            "matrix.json",
            "--run-id",
            "release-2",
            "--release-sha",
            RELEASE_SHA,
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
    assert report["environment"] == "prod"
    assert captured["client"] is sentinel
    assert captured["matrix"] is matrix
    assert captured["kwargs"] == {
        "run_id": "release-2",
        "release_sha": RELEASE_SHA,
        "server_build": SERVER_BUILD,
        "engine_version": "0.1.1+launch.999",
        "caller_session_id": "main-session",
        "timeout_seconds": 12.0,
        "poll_seconds": 2.0,
        "unsupported_observation_seconds": 4.0,
        "qualification": None,
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
            "--release-sha",
            RELEASE_SHA,
            "--poll-seconds",
            "0",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["failure_code"] == "poll_window_invalid"


def test_entrypoint_bounds_each_grant_consumption_window(monkeypatch, capsys) -> None:
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
            "release-window",
            "--release-sha",
            RELEASE_SHA,
            "--timeout-seconds",
            "901",
            "--qualification-candidate",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["failure_code"] == "qualification_window_invalid"


def test_entrypoint_refuses_release_mismatch_before_mutating_cli(
    monkeypatch, capsys
) -> None:
    matrix = AcceptanceMatrix(
        "yoke",
        (AcceptanceCell("codex-cli", "0.148.0-alpha.15", "create"),),
    )

    class _Client:
        def deployed_release(self):
            return {"server_build": "b" * 40, "engine_version": "0.1.1"}

        def call(self, *_args, **_kwargs):
            raise AssertionError("mutating CLI called")

    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: False)
    monkeypatch.setattr(acceptance, "_caller_session_id", lambda: "main-session")
    monkeypatch.setattr(
        acceptance, "_require_final_acceptance_environment", lambda: "prod"
    )
    monkeypatch.setattr(acceptance, "load_matrix", lambda _path: matrix)
    monkeypatch.setattr(
        acceptance,
        "YokeCliClient",
        lambda *, explicit_env: _Client() if explicit_env == "prod" else None,
    )
    monkeypatch.setattr(
        acceptance,
        "LiveAcceptanceDriver",
        lambda _client: (_ for _ in ()).throw(AssertionError("driver constructed")),
    )

    code = acceptance.main(
        [
            "--matrix",
            "matrix.json",
            "--run-id",
            "release-mismatch",
            "--release-sha",
            RELEASE_SHA,
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["failure_code"] == "deployed_release_mismatch"


def test_candidate_mode_refuses_prod_before_loading_or_constructing_cli(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: False)
    monkeypatch.setattr(acceptance, "_caller_session_id", lambda: "main-session")
    monkeypatch.setattr(acceptance.machine_config, "active_env", lambda: "prod")

    def _prod_connection(*, explicit_env=None):
        assert explicit_env == "prod"
        return {"transport": "https", "prod": True}

    monkeypatch.setattr(
        acceptance.machine_config,
        "active_connection",
        _prod_connection,
    )
    monkeypatch.setattr(
        acceptance,
        "load_candidate_matrix",
        lambda _path: (_ for _ in ()).throw(AssertionError("matrix loaded")),
    )
    monkeypatch.setattr(
        acceptance,
        "YokeCliClient",
        lambda: (_ for _ in ()).throw(AssertionError("CLI constructed")),
    )

    code = acceptance.main(
        [
            "--qualification-candidate",
            "--matrix",
            "matrix.json",
            "--run-id",
            "stage-only-proof",
            "--release-sha",
            RELEASE_SHA,
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["failure_code"] == "qualification_stage_required"


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
