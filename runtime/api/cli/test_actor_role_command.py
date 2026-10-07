"""CLI routing for setting a person's org role."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import actors
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY


def _capture(monkeypatch):
    captured = {}

    def dispatch_and_emit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(actors, "dispatch_and_emit", dispatch_and_emit)
    return captured


def test_actor_role_command_is_registered() -> None:
    function_id, adapter = SUBCOMMAND_REGISTRY[("actors", "role", "set")]
    assert function_id == "actors.role.set"
    assert adapter is actors.actors_role_set


def test_actor_id_form_reaches_registered_function(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    actor_id = 17
    assert actors.actors_role_set([str(actor_id), "--role", "viewer"]) == 0
    assert captured["function_id"] == "actors.role.set"
    assert captured["target"].kind == "global"
    assert captured["payload"] == {"actor_id": actor_id, "role": "viewer"}


def test_member_form_sends_the_email(monkeypatch) -> None:
    captured = _capture(monkeypatch)
    assert (
        actors.actors_role_set(["--member", "a@example.test", "--role", "admin"]) == 0
    )
    assert captured["payload"] == {"member_email": "a@example.test", "role": "admin"}


@pytest.mark.parametrize(
    "args",
    [["--role", "admin"], ["17", "--member", "a@example.test", "--role", "admin"]],
)
def test_exactly_one_person_reference_is_required(args) -> None:
    with pytest.raises(SystemExit, match="2"):
        actors.actors_role_set(args)
