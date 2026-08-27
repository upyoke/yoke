"""The public preview exposes dedicated broker preparation explicitly."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

from runtime.api.tools import session_control_live_acceptance_command as command
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
