"""The public preview exposes dedicated broker preparation explicitly."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

from runtime.api.tools import session_control_live_acceptance_command as command
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)
from runtime.api.tools.test_session_control_live_acceptance_command import (
    RELEASE_SHA,
    _argv,
    _bindings,
    _ready_decision,
)
from yoke_cli.commands.adapters.session_control_acceptance import (
    PREPARE_BROKER_FLAG,
)


def test_prepare_broker_flag_reaches_pre_hygiene(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(command, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        command,
        "validate_product_source",
        lambda _cwd, _release: SimpleNamespace(commit=RELEASE_SHA),
    )
    monkeypatch.setattr(command.sys, "stdin", io.StringIO(json.dumps(_bindings())))

    def _resolve(*_args, **kwargs):
        captured.update(kwargs)
        return _ready_decision()

    monkeypatch.setattr(command, "resolve_or_prepare_broker_binding", _resolve)

    assert command.main(_argv("--preview", PREPARE_BROKER_FLAG)) == 0
    assert captured["prepare"] is True
    assert captured["run_id"] == "release-proof"
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_idempotency_refusal_names_attempt_consumed_state_and_recovery(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(command, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        command,
        "validate_product_source",
        lambda _cwd, _release: SimpleNamespace(commit=RELEASE_SHA),
    )
    monkeypatch.setattr(command.sys, "stdin", io.StringIO(json.dumps(_bindings())))

    def _resolve(*_args, **_kwargs):
        raise AcceptanceContractError(
            "idempotency_conflict",
            surface="codex-cli",
            evidence={
                "owning_attempt_id": "attempt-one",
                "run_id": "release-proof",
                "run_consumed": False,
                "recovery": "Rerun preview with --prepare-broker to start a new attempt.",
            },
        )

    monkeypatch.setattr(command, "resolve_or_prepare_broker_binding", _resolve)

    assert command.main(_argv("--preview", PREPARE_BROKER_FLAG)) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["failure_code"] == "idempotency_conflict"
    assert report["owning_attempt_id"] == "attempt-one"
    assert report["run_id"] == "release-proof"
    assert report["run_consumed"] is False
    assert "--prepare-broker" in report["recovery"]
