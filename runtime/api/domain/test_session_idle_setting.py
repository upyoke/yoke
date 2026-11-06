"""Idle settings converge once while preserving each project's value."""

import importlib
import json

import pytest

from yoke_contracts.project_contract.project_keys import RECOGNIZED_PROJECT_KEYS

migration = importlib.import_module(
    "yoke_core.domain.migrations.0105_session_idle_setting"
)


@pytest.mark.parametrize(
    "settings,expected",
    [
        (
            {"steering_report_idle_minutes": 37, "wip_cap": 4},
            {"session_idle_minutes": 37, "wip_cap": 4},
        ),
        (
            {"steering_report_idle_minutes": 37, "session_idle_minutes": 6},
            {"session_idle_minutes": 6},
        ),
        ({"wip_cap": 4}, {"wip_cap": 4}),
    ],
)
def test_idle_setting_migration_is_idempotent(test_db, settings, expected):
    test_db.execute("DELETE FROM project_capabilities WHERE type='project-policy'")
    test_db.execute(
        "INSERT INTO project_capabilities (project_id,type,settings,created_at) VALUES (%s,%s,%s,CURRENT_TIMESTAMP)",
        (1, "project-policy", json.dumps(settings)),
    )
    for _ in range(2):
        migration.apply(test_db)
        migration.invariants(test_db)
        actual = test_db.execute(
            "SELECT settings FROM project_capabilities WHERE project_id=1 AND type='project-policy'"
        ).fetchone()[0]
        assert (json.loads(actual) if isinstance(actual, str) else actual) == expected
    assert "steering_report_idle_minutes" not in RECOGNIZED_PROJECT_KEYS
    assert RECOGNIZED_PROJECT_KEYS["session_idle_minutes"].default == 20
