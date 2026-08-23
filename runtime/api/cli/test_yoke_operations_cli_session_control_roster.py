"""CLI rendering contract for the enriched fleet session roster."""

from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest

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


FULL_SESSION_ID = "11111111-1111-4111-8111-111111111111"
FULL_MACHINE_ID = "22222222-2222-4222-8222-222222222222"


def test_roster_dispatches_existing_registered_read_and_renders_headed_table(
    monkeypatch,
    capsys,
) -> None:
    captured = {}
    response = SimpleNamespace(
        result={
            "fields": list(SESSION_CONTROL_ROSTER_FIELDS),
            "rows": [
                {
                    "session_id": FULL_SESSION_ID,
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
                    "machine_id": FULL_MACHINE_ID,
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
    rendered = capsys.readouterr().out
    lines = rendered.splitlines()
    assert lines[0] == "SESSIONS"
    assert "SESSION" in lines[1]
    assert "PROJECT" in lines[1]
    assert "MESSAGEABLE" in lines[1]
    assert FULL_SESSION_ID in rendered
    assert FULL_MACHINE_ID in rendered
    assert TEST_ITEM_REF in rendered
    assert "codex / codex-desktop" in rendered
    assert "connected" in rendered
    assert "yes" in rendered
    assert "|" not in rendered


def test_roster_has_explicit_empty_and_full_point_views() -> None:
    empty = io.StringIO()
    roster.write_roster_result(
        {"fields": list(SESSION_CONTROL_ROSTER_FIELDS), "rows": []},
        empty,
    )
    assert empty.getvalue() == "SESSIONS\nNo sessions found.\n"

    point = io.StringIO()
    roster.write_roster_result(
        {
            "fields": list(SESSION_CONTROL_ROSTER_FIELDS),
            "rows": [
                {
                    "session_id": "session-1",
                    "project": "yoke",
                    "executor": "claude-code",
                    "executor_surface": "claude-cli",
                    "executor_version": "2.1.241",
                    "machine_id": "machine-1",
                    "liveness": "active",
                    "relay": "connected",
                    "claims": [],
                    "messageability": {"messageable": True},
                    "ended_at": "",
                    "activity_at": "2026-08-23T12:00:00Z",
                }
            ],
        },
        point,
    )
    rendered = point.getvalue()
    assert "PROJECT" in rendered
    assert "RUNNER" in rendered
    assert "MESSAGEABLE" in rendered
    assert "claude-code / claude-cli" in rendered


def test_roster_point_lookup_dispatches_the_exact_session_filter(monkeypatch) -> None:
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(roster, "dispatch_and_emit", _dispatch)

    assert (
        roster.session_control_roster_list(
            ["--project", "yoke", "--session", "session-1", "--json"]
        )
        == 0
    )
    assert captured["function_id"] == "sessions.list"
    assert captured["payload"] == {
        "project": "yoke",
        "session_id": "session-1",
    }
    assert captured["json_mode"] is True


def test_registry_override_and_usage_map_are_ready_for_aggregation() -> None:
    function_id, adapter = SESSION_CONTROL_SUBCOMMAND_REGISTRY[("sessions", "list")]
    assert function_id == "sessions.list"
    assert adapter is roster.session_control_roster_list
    assert SESSION_CONTROL_USAGE_BY_FUNCTION_ID["sessions.list"].startswith(
        "yoke sessions list"
    )
    for function_id, _adapter in SESSION_CONTROL_SUBCOMMAND_REGISTRY.values():
        assert function_id in SESSION_CONTROL_USAGE_BY_FUNCTION_ID


def test_roster_help_explains_discovery_and_the_message_next_step(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        roster.session_control_roster_list(["--help"])

    assert exit_info.value.code == 0
    rendered = capsys.readouterr().out
    assert "Find registered top-level sessions" in rendered
    assert "yoke sessions list --liveness active" in rendered
    assert "yoke say --help" in rendered
