"""CLI rendering contract for the enriched fleet session roster."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from runtime.api.test_constants import TEST_ITEM_REF
from yoke_cli.commands.adapters import session_control_roster as roster
from yoke_cli.commands.adapters.session_control_usage import (
    SESSION_CONTROL_USAGE_BY_FUNCTION_ID,
)
from yoke_cli.commands.registry_session_control import (
    SESSION_CONTROL_SUBCOMMAND_REGISTRY,
)
from yoke_core.domain.session_control_roster import (
    SESSION_CONTROL_ROSTER_FIELDS,
)


def test_roster_dispatches_existing_registered_read_and_renders_all_columns(
    monkeypatch,
    capsys,
) -> None:
    captured = {}
    response = SimpleNamespace(
        result={
            "fields": list(SESSION_CONTROL_ROSTER_FIELDS),
            "rows": [
                {
                    "session_id": "session-1",
                    "project": "yoke",
                    "claims": [
                        {"target": TEST_ITEM_REF},
                        {"target": "feed"},
                    ],
                    "focus": TEST_ITEM_REF,
                    "role": "implementation",
                    "worktree": "/repo/.worktrees/item-42",
                    "executor": "codex",
                    "executor_surface": "codex-desktop",
                    "executor_version": "26.814.41407",
                    "machine_id": "machine-1",
                    "liveness": "active",
                    "relay": "connected",
                    "messageability": {
                        "messageable": True,
                        "relay_connected": True,
                    },
                }
            ],
        }
    )

    def _dispatch(**kwargs):
        captured.update(kwargs)
        kwargs["human_writer"](response, sys.stdout, sys.stderr)
        return 0

    monkeypatch.setattr(roster, "dispatch_and_emit", _dispatch)
    assert (
        roster.session_control_roster_list(
            [
                "--project",
                "yoke",
                "--liveness",
                "active",
                "--limit",
                "5",
            ]
        )
        == 0
    )

    assert captured["function_id"] == "sessions.list"
    assert captured["payload"] == {
        "project": "yoke",
        "liveness": "active",
        "limit": 5,
    }
    assert capsys.readouterr().out == (
        f"session-1|yoke|{TEST_ITEM_REF},feed|{TEST_ITEM_REF}|implementation|"
        "/repo/.worktrees/item-42|codex|codex-desktop|26.814.41407|"
        "machine-1|active|connected|"
        '{"messageable":true,"relay_connected":true}\n'
    )


def test_registry_override_and_usage_map_are_ready_for_aggregation() -> None:
    function_id, adapter = SESSION_CONTROL_SUBCOMMAND_REGISTRY[("sessions", "list")]
    assert function_id == "sessions.list"
    assert adapter is roster.session_control_roster_list
    assert SESSION_CONTROL_USAGE_BY_FUNCTION_ID["sessions.list"].startswith(
        "yoke sessions list"
    )
    for function_id, _adapter in SESSION_CONTROL_SUBCOMMAND_REGISTRY.values():
        assert function_id in SESSION_CONTROL_USAGE_BY_FUNCTION_ID
