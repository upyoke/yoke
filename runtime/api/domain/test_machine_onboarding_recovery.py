"""Machine handoffs follow the target project's receiving harness, not the server."""

import sqlite3

import pytest

from yoke_core.domain.machine_detail import _projects


def _session(executor, *, project_id=1, ended_at=None):
    return {
        "executor": executor,
        "project_id": project_id,
        "workspace": "/fixture/project",
        "ended_at": ended_at,
    }


def _recovery(sessions):
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE projects (id INTEGER, slug TEXT, name TEXT)")
        conn.execute("INSERT INTO projects VALUES (1, 'fixture', 'Fixture')")
        [project] = _projects(conn, {1}, [], sessions)
    assert project["checkout"] == ("/fixture/project" if sessions else None)
    assert "installed yoke skill" in project["recovery"]
    return project["recovery"]


@pytest.mark.parametrize("executor", ["codex", "codex-cli", "codex-desktop"])
def test_codex_machine_handoff_uses_native_skill_invocation(executor):
    recovery = _recovery([_session(executor)])
    assert "$yoke onboard" in recovery
    assert "/yoke onboard" not in recovery


@pytest.mark.parametrize("executor", ["claude-code", "claude-cli", "cursor"])
def test_slash_harnesses_keep_their_native_invocation(executor):
    recovery = _recovery([_session(executor)])
    assert "/yoke onboard" in recovery
    assert "$yoke onboard" not in recovery


@pytest.mark.parametrize(
    "sessions",
    [
        [],
        [_session("unknown")],
        [_session("codex", ended_at="2026-01-01")],
        [_session("codex"), _session("cursor")],
    ],
)
def test_unknown_or_ambiguous_receiving_harness_teaches_both_forms(sessions):
    recovery = _recovery(sessions)
    assert "Codex: $yoke onboard" in recovery
    assert "Claude Code/Cursor: /yoke onboard" in recovery


def test_other_projects_and_ended_sessions_do_not_choose_the_harness():
    recovery = _recovery(
        [
            _session("claude-code", project_id=2),
            _session("cursor", ended_at="2026-01-01"),
            _session("codex"),
        ]
    )
    assert "$yoke onboard" in recovery
    assert "/yoke onboard" not in recovery
