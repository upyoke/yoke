"""After 0119, a live execution resumes on its rewritten roster.

A roster frozen before the change carried host names and a local Command's
inert ``os``. The migration rewrites the roster and its requirements with
one conversion, so the roster ``begin`` rebuilds on resume digests to the
stored value: no ``qa_roster_changed``, an unchanged execution target (so a
deployment execution is not re-frozen) and the same queue place.
"""

from __future__ import annotations

import json

from runtime.api.domain.machine_qa_session_seed import seed_registered_qa_launch
from runtime.api.domain.migration_qa_hosts_by_os_test_support import migration
from runtime.api.domain.qa_plan_execution_authority_test_support import (
    _materialize_two_cases,
    _result,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_host_set_turns import execution_place
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import canonical, roster_digest
from yoke_core.domain.qa_plan_execution_target_snapshot import (
    execution_target_for_roster,
    validate_execution_snapshot,
)

OWNER = {"actor_id": "7", "session_id": "hosts-by-os-session"}
_LEGACY = {"os": "linux", "platform": "linux"}
_LEGACY_KIND = "test-machine:lin-1"


def _begin(conn, item_id):
    seed_registered_qa_launch(conn, OWNER["session_id"], actor_id=int(OWNER["actor_id"]))
    return begin_plan_execution(conn, item_id=item_id, transition_id="implemented", **OWNER)


def _register(conn, name, system):
    settings = {
        "resource_name": name, "host": f"{name}.local", "user": "yoke-test",
        "os": system, "operating_notes": "Shared lab host.",
    }
    conn.execute(
        "INSERT INTO test_machines(name,settings,created_at) VALUES(%s,%s,now())",
        (name, json.dumps(settings, separators=(",", ":"), sort_keys=True)),
    )


def _legacy(conn, execution, requirement_id, legacy=_LEGACY, drop=()):
    """Put the pre-change shape back on one case: its plan row, requirement and roster entry."""

    def old(config):
        return {**{k: v for k, v in config.items() if k not in drop}, **legacy}

    (config, kinds, plan_id, key) = conn.execute(
        "SELECT method_config,capability_requirements,plan_id,plan_case_key "
        "FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    config = old(json.loads(config))
    kinds = [*json.loads(kinds or "[]"), _LEGACY_KIND]
    conn.execute(
        "UPDATE qa_requirements SET method_config=%s,capability_requirements=%s WHERE id=%s",
        (canonical(config), json.dumps(kinds), requirement_id),
    )
    conn.execute(
        "UPDATE qa_plan_cases SET method_config=%s WHERE plan_id=%s AND case_key=%s",
        (canonical(old(json.loads(conn.execute(
            "SELECT method_config FROM qa_plan_cases WHERE plan_id=%s AND case_key=%s",
            (plan_id, key),
        ).fetchone()[0]))), plan_id, key),
    )
    roster = [
        {
            **entry,
            "method_config": old(entry["method_config"]),
            "required_capability_kinds": [*entry["required_capability_kinds"], _LEGACY_KIND],
        }
        if entry["requirement_id"] == requirement_id
        else entry
        for entry in execution["roster"]
    ]
    conn.execute(
        "UPDATE qa_plan_executions SET roster_json=%s,roster_digest=%s WHERE id=%s",
        (canonical(roster), roster_digest(roster), execution["id"]),
    )


def _stored(conn, execution_id):
    row = select_plan_execution(conn, execution_id, lock=False)
    conn.rollback()
    return row


def test_resume_after_migration_keeps_roster_target_and_place():
    with test_database() as conn:
        first, second = _materialize_two_cases(conn, item_id=5641)
        execution = _begin(conn, 5641)
        advance_plan_execution(
            conn, execution, ordinal=0, requirement_id=first, result=_result(first)
        )
        frozen = _stored(conn, str(execution["id"]))
        _register(conn, "lin-1", "linux")
        _register(conn, "lin-2", "linux")
        _legacy(conn, frozen, second)
        conn.execute(
            "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,queued_at,"
            "qa_plan_execution_id,state,resume_command,rationale) "
            "VALUES('w-1','lin-1',%s,7,'2026-11-01T08:00:00Z',%s,'waiting','resume','busy')",
            (OWNER["session_id"], execution["id"]),
        )
        conn.commit()
        place = execution_place(conn, execution, ["lin-1"])

        migration().apply(conn)
        migration().invariants(conn)
        conn.commit()

        migrated = _stored(conn, str(execution["id"]))
        assert migrated["roster"] == frozen["roster"]
        assert migrated["roster_digest"] == frozen["roster_digest"]
        assert validate_execution_snapshot(migrated, migrated["roster"]) is not None
        target_digest = execution_target_for_roster(migrated["roster"])[1]
        assert target_digest == migrated["execution_target_digest"]
        assert execution_place(conn, execution, ["lin-1", "lin-2"]) == place
        needs = conn.execute(
            "SELECT test_machine,need_id,queued_at FROM qa_test_machine_waits "
            "WHERE qa_plan_execution_id=%s ORDER BY test_machine",
            (execution["id"],),
        ).fetchall()
        assert [row[0] for row in needs] == ["lin-1", "lin-2"]
        assert needs[0][1] == needs[1][1] is not None
        assert needs[0][2] == needs[1][2] == place
        conn.commit()

        resumed = _begin(conn, 5641)

        assert resumed["id"] == execution["id"]
        assert int(resumed["cursor_ordinal"]) == 1


def test_a_pinned_host_command_resumes_selecting_by_os():
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_plan_attachments import materialize_for_item, set_project_default
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

    with test_database() as conn:
        _register(conn, "lin-1", "linux")
        _register(conn, "lin-2", "linux")
        insert_item(conn, id=5642, title="Run a host Command", workflow_id="issue")
        plan = create_plan(conn, project="yoke", slug="host-command-5642", name="Host Command")
        replace_plan_cases(conn, plan_id=int(plan["id"]), cases=[{
            "case_key": "host-command", "position": 1, "method_id": "command",
            "instructions": "Run on a Linux host.", "expected_outcome": "It passes.",
            "method_config": {"command": "true", "os": "linux"},
            "host_baselines": ["fresh-host"],
        }])
        set_project_default(conn, plan_id=int(plan["id"]), workflow_id="issue",
                            transition_id="implemented")
        (requirement,) = materialize_for_item(
            conn, item_id=5642, transition_id="implemented"
        )["created_requirement_ids"]
        execution = _begin(conn, 5642)
        frozen = _stored(conn, str(execution["id"]))
        assert frozen["roster"][0]["method_config"]["os"] == "linux"
        _legacy(conn, frozen, int(requirement), drop=("os",), legacy={
            "test_machine": "lin-1", "test_machine_reason": "the lab host",
        })
        conn.commit()

        migration().apply(conn)
        migration().invariants(conn)
        conn.commit()

        migrated = _stored(conn, str(execution["id"]))
        assert migrated["roster"] == frozen["roster"]
        assert migrated["roster_digest"] == frozen["roster_digest"]
        assert _begin(conn, 5642)["id"] == execution["id"]


def test_a_three_name_set_wait_is_admitted_on_any_matching_hosts(
    test_db, tmp_path, monkeypatch
):
    from datetime import timedelta

    from runtime.api.domain.machine_qa_host_test_support import (
        TEST_MACHINE_SETTINGS,
        configure_test_machine,
        verify_fixture_host,
    )
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session
    from yoke_contracts.timestamps import utc_now
    from yoke_core.domain.coordination_claims import acquire, active_claim
    from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
    from yoke_core.domain.qa_host_slot_turns import assign_slot_hosts
    from yoke_core.domain.work_claim_targets import make_qa_admission_target

    configure_test_machine(test_db, tmp_path, monkeypatch)
    for name, system in (("lin-a", "linux"), ("lin-b", "linux"), ("mac-a", "macos"),
                         ("win-a", "windows"), ("win-b", "windows")):
        replace_test_machine_settings(
            test_db, power_project="yoke", test_machine=name, base_settings=None,
            settings={**TEST_MACHINE_SETTINGS, "resource_name": name, "os": system},
        )
        verify_fixture_host(test_db, name)
    seed_qa_session(test_db, "walker", "holder", messageable=True)
    roster = [{
        "requirement_id": 1, "runner_id": "agent_mission", "host_baseline": "fresh-host",
        "method_config": {"test_machine": "mac-a", "test_machines": ["lin-a", "mac-a", "win-a"]},
    }]
    created = utc_now() - timedelta(minutes=1)
    test_db.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,actor_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES('set-exec','run-1','item-qa',7,'walker','1',%s,%s,0,'waiting',%s,%s)",
        (roster_digest(roster), canonical(roster), created, created),
    )
    # Two named hosts are busy, so only the hosts 0119 adds can serve the set.
    for name in ("lin-a", "win-a"):
        acquire(test_db, make_qa_admission_target(name), "holder")
    for name in ("lin-a", "mac-a", "win-a"):
        test_db.execute(
            "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,queued_at,"
            "qa_plan_execution_id,state,resume_command,rationale) "
            "VALUES(%s,%s,'walker',1,%s,'set-exec','waiting','resume','set busy')",
            (f"w-{name}", name, created),
        )
    test_db.commit()

    migration().apply(test_db)
    test_db.commit()

    needs = dict(test_db.execute(
        "SELECT test_machine,need_id FROM qa_test_machine_waits "
        "WHERE qa_plan_execution_id='set-exec'"
    ).fetchall())
    # The fixture's own macOS host joins the macos slot beside mac-a.
    assert sorted(needs) == ["lin-a", "lin-b", "mac-a", "mac-mini-lab", "win-a", "win-b"]
    assert needs["lin-a"] == needs["lin-b"] and needs["win-a"] == needs["win-b"]
    assert needs["mac-a"] == needs["mac-mini-lab"]
    assert len({needs["lin-a"], needs["mac-a"], needs["win-a"]}) == 3

    assert assign_slot_hosts(test_db, {"id": "set-exec"}) is True
    reserved = test_db.execute(
        "SELECT test_machine FROM qa_test_machine_waits "
        "WHERE qa_plan_execution_id='set-exec' AND state='reserved' ORDER BY test_machine"
    ).fetchall()
    assert [row[0] for row in reserved] == ["lin-b", "mac-a", "win-b"]
    for name in ("lin-b", "mac-a", "win-b"):
        assert active_claim(test_db, make_qa_admission_target(name)).session_id == "walker"
