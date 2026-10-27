"""Stored hostless missions converge without changing judged or hosted evidence."""

import importlib
import json

from runtime.api.domain.test_agent_mission_controller import _mission

MIGRATION = importlib.import_module("yoke_core.domain.migrations.0092_controller_missions")


def test_migration_clears_hostless_starting_state_and_machine_capability(test_db):
    execution = _mission(test_db)
    requirement_id = execution["roster"][0]["requirement_id"]
    test_db.execute(
        "UPDATE qa_requirements SET capability_requirements=%s,starting_state='as_is',"
        "starting_state_reason='legacy' WHERE id=%s",
        (json.dumps(["browser-control", "test-machine"]), requirement_id),
    )
    test_db.execute(
        "UPDATE qa_plan_cases SET starting_state='as_is',starting_state_reason='legacy' "
        "WHERE plan_id=%s", (execution["standalone_plan_id"],),
    )
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    MIGRATION.apply(test_db)
    assert test_db.execute(
        "SELECT capability_requirements,starting_state,starting_state_reason "
        "FROM qa_requirements WHERE id=%s", (requirement_id,),
    ).fetchone() == ('["browser-control"]', None, None)
    assert test_db.execute(
        "SELECT starting_state,starting_state_reason FROM qa_plan_cases WHERE plan_id=%s",
        (execution["standalone_plan_id"],),
    ).fetchone() == (None, None)


def test_migration_preserves_explicit_hosts_and_waived_requirements(test_db):
    execution = _mission(test_db)
    requirement_id = execution["roster"][0]["requirement_id"]
    for config, waiver in [({"test_machine": "test-mac"}, None), ({}, "2026-10-01T00:00:00Z")]:
        test_db.execute(
            "UPDATE qa_requirements SET method_config=%s,waived_at=%s,starting_state='as_is',"
            "starting_state_reason='preserve',capability_requirements=%s WHERE id=%s",
            (json.dumps(config), waiver, '["browser-control", "test-machine"]', requirement_id),
        )
        MIGRATION.apply(test_db)
        assert test_db.execute(
            "SELECT starting_state,starting_state_reason,capability_requirements "
            "FROM qa_requirements WHERE id=%s", (requirement_id,),
        ).fetchone() == ('as_is', 'preserve', '["browser-control", "test-machine"]')
