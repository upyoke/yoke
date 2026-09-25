"""CLI routing for the governed actor lifecycle."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import actors
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY


def test_actor_state_command_is_registered() -> None:
    function_id, adapter = SUBCOMMAND_REGISTRY[("actors", "state", "set")]
    assert function_id == "actors.state.set"
    assert adapter is actors.actors_state_set


def test_system_retirement_confirmation_reaches_registered_function(
    monkeypatch,
) -> None:
    captured = {}
    actor_id = 17

    def dispatch_and_emit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(actors, "dispatch_and_emit", dispatch_and_emit)
    assert (
        actors.actors_state_set(
            [str(actor_id), "--disable", "--confirm-system-retirement"]
        )
        == 0
    )
    assert captured["function_id"] == "actors.state.set"
    assert captured["target"].kind == "global"
    assert captured["payload"] == {
        "actor_id": actor_id,
        "enabled": False,
        "confirm_system_retirement": True,
    }


def test_confirmation_cannot_be_used_with_enable() -> None:
    actor_id = 17
    with pytest.raises(SystemExit, match="2"):
        actors.actors_state_set(
            [str(actor_id), "--enable", "--confirm-system-retirement"]
        )
