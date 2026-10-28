"""Plan-group formation cost does not grow with the run's members."""

from collections import Counter

from runtime.api.domain.test_deployment_qa_plan_groups import _attach
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_shipping_reads import CountedConnection
from yoke_core.domain import schema_common_postgres as schema
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups


def _seed_wide(conn, run_id, members, plans):
    stages = _stages(plans[0])
    stages[1].pop("cases")
    _seed_run(conn, run_id=run_id, stages=stages, members=members)
    for member in members:
        for plan in plans:
            _attach(conn, member, plan)


def test_44_member_group_formation_reads_as_much_as_a_4_member_one(
    test_db, monkeypatch
):
    plans = [_plan(test_db, f"shared-probe-{n}") for n in range(2)]
    _seed_wide(test_db, "run-narrow-groups", tuple(range(11001, 11005)), plans)
    _seed_wide(test_db, "run-wide-groups", tuple(range(11101, 11145)), plans)
    schema_reads = Counter()
    columns = schema._read_columns
    tables = schema._read_table_exists

    def read_columns(conn, table):
        schema_reads[("columns", table)] += 1
        return columns(conn, table)

    def read_table(conn, table):
        schema_reads[("table", table)] += 1
        return tables(conn, table)

    monkeypatch.setattr(schema, "_read_columns", read_columns)
    monkeypatch.setattr(schema, "_read_table_exists", read_table)

    def form(run_id):
        schema_reads.clear()
        counted = CountedConnection(test_db)
        created = ensure_groups(counted, run_id, "item-qa")
        test_db.commit()
        assert len(created) == 2  # one row per plan, none per member
        assert not schema_reads or max(schema_reads.values()) == 1
        return sum(counted.queries.values())

    assert form("run-wide-groups") == form("run-narrow-groups")
    assert ensure_groups(test_db, "run-wide-groups", "item-qa") == []
    groups = run_groups(test_db, ["run-wide-groups"], "item-qa")
    assert sorted(g.plan_id for g in groups) == sorted(plans)
    assert all(len(g.requirement_ids) == 1 for g in groups)


def test_methodless_member_obligation_keeps_the_plan_group(test_db):
    from runtime.api.domain.test_deployment_qa_admission_execution import (
        _original_requirement,
    )
    from runtime.api.domain.test_deployment_qa_plan_groups import (
        MEMBERS,
        RUN,
        _begin,
        _seed,
    )
    from yoke_core.domain.deployment_requirement_snapshots import (
        requirement_selection,
        snapshot_member_requirements,
    )

    plan_id = _seed(test_db)
    member = MEMBERS[1]
    requirement_id = _original_requirement(test_db, item_id=member, method_id=None)
    snapshot = snapshot_member_requirements(
        test_db,
        run_id=RUN,
        item_id=member,
        selection_json=requirement_selection(requirement_ids=(requirement_id,)),
    )
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s "
        "WHERE run_id=%s AND item_id=%s",
        (snapshot, RUN, member),
    )
    test_db.commit()

    ids = ensure_groups(test_db, RUN, "item-qa")
    test_db.commit()
    assert len(ids) == 1
    row = test_db.execute(
        "SELECT plan_id,deployment_member_item_id FROM qa_requirements WHERE id=%s",
        (ids[0],),
    ).fetchone()
    assert tuple(row) == (plan_id, None)
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s "
            "AND plan_id IS NOT NULL AND deployment_member_item_id=%s",
            (RUN, member),
        ).fetchone()[0]
        == 0
    )
    execution = _begin(test_db, member)
    assert execution["deployment_member_item_id"] is None
    assert [row["requirement_id"] for row in execution["roster"]] == ids
