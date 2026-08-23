"""Environment authority tests for Fleet live acceptance."""

from __future__ import annotations

import json

from runtime.api.tools import session_control_live_acceptance as acceptance
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceMatrix,
)


RELEASE_SHA = "a" * 40


def _argv() -> list[str]:
    return [
        "--matrix",
        "matrix.json",
        "--run-id",
        "prod-proof",
        "--release-sha",
        RELEASE_SHA,
    ]


def test_full_runner_refuses_non_prod_before_loading_or_constructing_cli(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: False)
    monkeypatch.setattr(acceptance, "_caller_session_id", lambda: "main-session")
    monkeypatch.setattr(acceptance.machine_config, "active_env", lambda: "stage")
    monkeypatch.setattr(
        acceptance.machine_config,
        "active_connection",
        lambda *, explicit_env: {"transport": "https", "prod": False},
    )
    monkeypatch.setattr(
        acceptance,
        "load_matrix",
        lambda _path: (_ for _ in ()).throw(AssertionError("matrix loaded")),
    )
    monkeypatch.setattr(
        acceptance,
        "YokeCliClient",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("CLI constructed")),
    )

    code = acceptance.main(_argv())

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["failure_code"] == "final_acceptance_prod_required"


def test_full_runner_pins_prod_after_active_env_switch(monkeypatch, capsys) -> None:
    matrix = AcceptanceMatrix(
        "yoke",
        (AcceptanceCell("codex-desktop", "26.814.41407", "create"),),
    )
    state = {"active_env": "prod"}
    captured: dict[str, object] = {}

    class _Client:
        def deployed_release(self):
            return {"server_build": RELEASE_SHA, "engine_version": "0.1.1"}

    class _Driver:
        def __init__(self, client) -> None:
            captured["client"] = client

        def run(self, supplied, **_kwargs):
            assert supplied is matrix
            return {"schema": 1, "status": "passed", "cells": []}

    def _connection(*, explicit_env=None):
        assert explicit_env == "prod"
        state["active_env"] = "stage"
        return {"transport": "https", "prod": True}

    def _client(*, explicit_env=None):
        assert state["active_env"] == "stage"
        captured["explicit_env"] = explicit_env
        return _Client()

    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: False)
    monkeypatch.setattr(acceptance, "_caller_session_id", lambda: "main-session")
    monkeypatch.setattr(
        acceptance.machine_config, "active_env", lambda: state["active_env"]
    )
    monkeypatch.setattr(acceptance.machine_config, "active_connection", _connection)
    monkeypatch.setattr(acceptance, "load_matrix", lambda _path: matrix)
    monkeypatch.setattr(acceptance, "YokeCliClient", _client)
    monkeypatch.setattr(acceptance, "LiveAcceptanceDriver", _Driver)

    code = acceptance.main(_argv())

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert captured["explicit_env"] == "prod"
    assert report["environment"] == "prod"
