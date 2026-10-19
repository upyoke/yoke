"""Membership writes cost the same control-plane statements for one member or many.

Each round trip to a hosted control plane costs tens of milliseconds, so a
takeover, an admission or an executing transition that repeats its reads and
writes per member grows with the release. These count every statement the
operation sends and compare a small release with a larger one.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.tools.read_query_profile import CountedConnection
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain import deployment_run_composition_freeze as composition
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_member_admission import (
    MemberAdmission,
    admit_run_items,
)
from yoke_core.domain.deployment_run_start import _admit
from yoke_core.domain.deployment_run_target_takeover import take_over_waiting_run
from yoke_core.domain.schema_read_scope import composition_reads

SMALL, LARGE = 2, 5


def _statements(conn: Any, operation: Callable[[Any], Any]) -> int:
    """Statements *operation* sends inside one production-shaped read scope."""
    counted = CountedConnection(conn)
    with composition_reads():
        operation(counted)
    conn.commit()
    return sum(counted.counts.values())


def _members(base: int, count: int) -> list[int]:
    return [base + offset for offset in range(count)]


def _waiting_run(conn: Any, name: str, members: list[int]) -> str:
    """An older run waiting only on item QA, and a newer run on its target."""
    old, new = f"run-{name}-old", f"run-{name}-new"
    plan = create_smoke_plan(conn, project="yoke", slug=f"smoke-{old}")
    seed_run_standing_on_qa_stage(
        conn,
        run_id=old,
        project="yoke",
        stages=item_qa_stage_definitions(plan),
        members=tuple(members),
        lineage="b" * 40,
    )
    conn.execute(
        "UPDATE items SET status='release',deployment_flow=%s WHERE id=ANY(%s)",
        (f"flow-{old}", members),
    )
    for member in members:
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=old,
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=member,
        )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,"
        "'created',created_at FROM deployment_runs WHERE id=%s",
        (new, "c" * 40, old),
    )
    conn.commit()
    return new


def _created_run(conn: Any, name: str, members: list[int]) -> str:
    """A created run whose flow takes custody, and delivery-ready items."""
    run_id, flow = f"run-{name}", f"flow-{name}"
    stages = [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "deploy",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version,takes_delivery_custody) "
        "VALUES (%s,1,%s,'',%s,%s,'disabled',2,1)",
        (flow, flow, json.dumps(stages), "2026-09-14T00:00:00Z"),
    )
    for item_id in members:
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="blitz",
            status="implementing",
            deployment_flow=flow,
        )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at,composition_resolution) VALUES "
        "(%s,1,%s,%s,'created',%s,'baseline attested')",
        (run_id, flow, "a" * 40, "2026-09-14T00:00:00Z"),
    )
    conn.commit()
    return run_id


def _admit_all(run_id: str, members: list[int]) -> Callable[[Any], Any]:
    return lambda conn: admit_run_items(
        conn, run_id=run_id, members=[MemberAdmission(item) for item in members]
    )


def test_takeover_cost_does_not_grow_with_its_moving_members(test_db, monkeypatch):
    monkeypatch.setattr(
        containment,
        "candidate_contains_commit",
        lambda *_a, **_k: containment.ContainmentVerdict(
            containment.CONTAINED, reason=""
        ),
    )
    costs = []
    for name, members in (
        ("takeover-small", _members(9900, SMALL)),
        ("takeover-large", _members(9910, LARGE)),
    ):
        new = _waiting_run(test_db, name, members)
        costs.append(
            _statements(
                test_db,
                lambda conn: take_over_waiting_run(
                    conn, new, session_id=DRIVER_SESSION, actor_id=1
                ),
            )
        )
        moved = test_db.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (new,)
        ).fetchall()
        assert sorted(int(row["item_id"]) for row in moved) == members
    assert costs[0] == costs[1]


def test_admission_cost_does_not_grow_with_its_members(test_db):
    small = _created_run(test_db, "admit-small", _members(9930, SMALL))
    large = _created_run(test_db, "admit-large", _members(9940, LARGE))

    assert _statements(test_db, _admit_all(small, _members(9930, SMALL))) == (
        _statements(test_db, _admit_all(large, _members(9940, LARGE)))
    )


def test_executing_transition_cost_does_not_grow_with_its_members(test_db, monkeypatch):
    monkeypatch.setattr(
        composition,
        "record_carried_work",
        lambda _conn, _run: {
            "schema": 1,
            "derivation": {"contents_known": True, "reason": "test-fixture"},
            "items": [],
            "commits": [],
        },
    )
    costs = []
    for name, members in (
        ("start-small", _members(9950, SMALL)),
        ("start-large", _members(9960, LARGE)),
    ):
        run_id = _created_run(test_db, name, members)
        _statements(test_db, _admit_all(run_id, members))
        costs.append(_statements(test_db, lambda conn: _admit(conn, run_id, None)))
        status = test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()
        assert status["status"] == "executing"
    assert costs[0] == costs[1]


def test_admission_pins_completion_defaults_before_deriving_selections(
    test_db, monkeypatch
):
    """Selection reads the pin admission retains, even if the default moves."""
    from yoke_core.domain import deployment_member_post_deploy_admission as admission
    from yoke_core.domain import deployment_run_member_admission as member_admission
    from yoke_core.domain import workflow_project_defaults as defaults

    members = _members(9970, SMALL)
    run_id = _created_run(test_db, "admit-pin", members)
    test_db.execute(
        "UPDATE items SET deployment_flow=NULL WHERE id=ANY(%s)", (members,)
    )
    test_db.commit()
    default = ["flow-admit-pin"]
    monkeypatch.setattr(
        defaults, "get_delivery_default", lambda conn, **kwargs: default[0]
    )
    derive = admission.post_deploy_admission_sets

    def changed_default(conn, **kwargs):
        default[0] = "changed-after-admission-began"
        return derive(conn, **kwargs)

    monkeypatch.setattr(member_admission, "post_deploy_admission_sets", changed_default)
    _statements(test_db, _admit_all(run_id, members))

    pins = test_db.execute(
        "SELECT deployment_flow FROM items WHERE id=ANY(%s)", (members,)
    ).fetchall()
    assert [row["deployment_flow"] for row in pins] == ["flow-admit-pin"] * SMALL


@pytest.mark.parametrize("refused_item", [0, 1])
def test_a_refusing_member_names_itself_and_admits_nothing(test_db, refused_item):
    members = _members(9980, SMALL)
    run_id = _created_run(test_db, f"admit-refused-{refused_item}", members)
    test_db.execute(
        "UPDATE items SET status='cancelled' WHERE id=%s", (members[refused_item],)
    )
    test_db.commit()
    seen = []

    def refused(item_id, exc):
        seen.append(item_id)
        return ValueError(f"refused {item_id}: {exc}")

    with pytest.raises(ValueError, match=f"refused {members[refused_item]}"):
        admit_run_items(
            test_db,
            run_id=run_id,
            members=[MemberAdmission(item) for item in members],
            refused=refused,
        )
    test_db.rollback()
    assert seen == [members[refused_item]]
    assert not test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchall()
