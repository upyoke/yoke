"""Checkout reassignment changes machine routing without steering authority."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers import machine_config_write as handlers
from runtime.api.domain.test_machine_config_writer_projects import (
    home as machine_home,
    _config,
    _seed_https,
)


home = machine_home


def _request(payload: dict, *, session_id: str = "") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="project.register.run",
        actor=ActorContext(actor_id=None, session_id=session_id),
        target=TargetRef(kind="global"),
        payload=payload,
    )


@pytest.mark.parametrize("session_id", ["s1", ""])
@pytest.mark.parametrize("reassign", [True, False])
def test_reassignment_requires_explicit_flag_without_a_seat(
    home, tmp_path, session_id, reassign
):
    _seed_https(home, tmp_path)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    handlers.machine_config_writer.register_project(old, 7)
    before = _config(home)
    outcome = handlers.handle_project_register(_request(
        {"repo_root": str(new), "project_id": 7, "reassign": reassign},
        session_id=session_id,
    ))
    if reassign:
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["checkout"] == str(new.resolve())
        assert _config(home)["connection_projects"]["stage"] == [
            {"checkout": str(new.resolve()), "project_id": 7}
        ]
    else:
        assert not outcome.primary_success
        assert outcome.error.code == "machine_config_write_refused"
        assert str(old.resolve()) in outcome.error.message
        assert "project register --reassign" in outcome.error.message
        assert "steering" not in outcome.error.message
        assert _config(home) == before


def test_cli_reassignment_writes_machine_config_without_a_seat(home, tmp_path, capsys):
    from yoke_cli.commands.adapters import config_write_project as cli

    _seed_https(home, tmp_path)
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    handlers.machine_config_writer.register_project(old, 7)
    assert cli.project_register([str(new), "--project-id", "7", "--reassign", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["checkout"] == str(new.resolve())
    assert _config(home)["connection_projects"]["stage"][0]["checkout"] == str(new.resolve())


def test_registration_help_teaches_explicit_move_without_seat(capsys):
    from yoke_cli.commands.adapters import config_write_project as cli

    with pytest.raises(SystemExit) as stopped:
        cli.project_register(["--help"])
    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "--reassign" in output
    assert "steering" not in output
