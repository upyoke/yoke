"""Registered command to executable QA-plan migration tests."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_command_plans import (
    list_registered_commands_for_project_id,
)
from yoke_core.domain.qa_command_plan_migration import (
    ensure_registered_command_plan,
    migrate_registered_commands,
)


def test_registered_commands_migrate_one_to_one_and_retire_storage() -> None:
    with test_database() as conn:
        conn.execute(
            "INSERT INTO project_structure("
            "project_id, family, attachment_value, attachment_kind, "
            "entry_key, payload, created_at, updated_at"
            ") VALUES (1, 'command_definitions', 'project', '', 'full', "
            "%s, '2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z')",
            (json.dumps({"command": "python3 -m pytest"}),),
        )
        conn.commit()
        result = migrate_registered_commands(conn)
        plan = conn.execute(
            "SELECT id, slug FROM qa_plans "
            "WHERE project_id=1 AND slug='registered-command-full'"
        ).fetchone()
        case = conn.execute(
            "SELECT method_id, method_config FROM qa_plan_cases "
            "WHERE plan_id=%s",
            (int(plan["id"]),),
        ).fetchone()
        defaults = conn.execute(
            "SELECT workflow_id, transition_id FROM qa_plan_project_defaults "
            "WHERE plan_id=%s ORDER BY workflow_id",
            (int(plan["id"]),),
        ).fetchall()
        legacy_count = conn.execute(
            "SELECT COUNT(*) FROM project_structure "
            "WHERE family='command_definitions'"
        ).fetchone()[0]
        compatibility_commands = list_registered_commands_for_project_id(
            conn, 1,
        )

    assert result["retired_legacy_rows"] == 1
    assert case["method_id"] == "command"
    assert json.loads(case["method_config"])["command"] == (
        "python3 -m pytest"
    )
    assert {row["workflow_id"] for row in defaults} == {
        "blitz", "dash", "epic", "issue",
    }
    assert {
        (row["workflow_id"], row["transition_id"]) for row in defaults
    } == {
        ("blitz", "done"),
        ("dash", "done"),
        ("epic", "reviewed-implementation"),
        ("issue", "reviewed-implementation"),
    }
    assert legacy_count == 0
    assert compatibility_commands == {
        "full": "python3 -m pytest"
    }


def test_merge_verification_migrates_to_release_command_plan() -> None:
    with test_database() as conn:
        conn.execute(
            "INSERT INTO project_structure("
            "project_id, family, attachment_value, attachment_kind, "
            "entry_key, payload, created_at, updated_at"
            ") VALUES (1, 'merge_verification', 'project', '', '', "
            "%s, '2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z')",
            (json.dumps({
                "command": "python3 -m pytest -q",
                "timeout_seconds": 900,
            }),),
        )
        conn.commit()
        result = migrate_registered_commands(conn)
        plan = conn.execute(
            "SELECT id FROM qa_plans "
            "WHERE project_id=1 AND slug='pre-merge-verification'"
        ).fetchone()
        case = conn.execute(
            "SELECT method_id, method_config FROM qa_plan_cases "
            "WHERE plan_id=%s",
            (int(plan["id"]),),
        ).fetchone()
        defaults = conn.execute(
            "SELECT workflow_id, transition_id FROM qa_plan_project_defaults "
            "WHERE plan_id=%s ORDER BY workflow_id",
            (int(plan["id"]),),
        ).fetchall()
        legacy_count = conn.execute(
            "SELECT COUNT(*) FROM project_structure "
            "WHERE family='merge_verification'"
        ).fetchone()[0]

    config = json.loads(case["method_config"])
    assert result["retired_legacy_rows"] == 1
    assert case["method_id"] == "command"
    assert config == {
        "command": "python3 -m pytest -q",
        "execution_point": "post_rebase_merge",
        "timeout_seconds": 900,
    }
    assert {
        (row["workflow_id"], row["transition_id"]) for row in defaults
    } == {
        ("epic", "release"),
        ("issue", "release"),
    }
    assert legacy_count == 0


def test_current_model_seed_converges_without_legacy_settings() -> None:
    with test_database() as conn:
        first = ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="full",
            command="python3 -m pytest",
        )
        second = ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="full",
            command="python3 -m pytest",
        )
        legacy = conn.execute(
            "SELECT COUNT(*) FROM project_structure "
            "WHERE family='command_definitions'"
        ).fetchone()[0]
        defaults = conn.execute(
            "SELECT workflow_id, transition_id "
            "FROM qa_plan_project_defaults WHERE plan_id=%s",
            (int(first["plan_id"]),),
        ).fetchall()

    assert second["plan_id"] == first["plan_id"]
    assert legacy == 0
    assert {
        (row["workflow_id"], row["transition_id"]) for row in defaults
    } == {
        ("blitz", "done"),
        ("dash", "done"),
        ("epic", "reviewed-implementation"),
        ("issue", "reviewed-implementation"),
    }


def test_invalid_legacy_row_is_not_retired() -> None:
    with test_database() as conn:
        conn.execute(
            "INSERT INTO project_structure("
            "project_id, family, attachment_value, attachment_kind, "
            "entry_key, payload, created_at, updated_at"
            ") VALUES (1, 'command_definitions', 'project', '', 'full', "
            "%s, '2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z')",
            (json.dumps({"command": ""}),),
        )
        conn.commit()
        with pytest.raises(RuntimeError, match="could not be migrated"):
            migrate_registered_commands(conn)
        legacy = conn.execute(
            "SELECT COUNT(*) FROM project_structure "
            "WHERE family='command_definitions'"
        ).fetchone()[0]

    assert legacy == 1
