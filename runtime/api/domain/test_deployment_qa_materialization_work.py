"""Materialization bounds shared-member selection to one run/stage projection."""

import pytest

from collections import Counter
from time import perf_counter

from runtime.api.domain.test_deployment_qa_shared_plans import _attach
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain import deployment_qa_shared_plans as shared
from yoke_core.domain import deployment_qa_plan_selection as selection
from yoke_core.domain import deployment_qa_materialization_projection as projection
from yoke_core.domain import schema_common_postgres as schema
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)


def test_shared_44_member_materialization_reuses_projection_and_discards_it(
    test_db, monkeypatch
):
    plans = [_plan(test_db, f"shared-probe-{n}") for n in range(2)]
    stages = _stages(plans[0])
    stages[1].pop("cases")
    members = tuple(range(11001, 11045))
    run_id = "run-materialization-work"
    _seed_run(test_db, run_id=run_id, stages=stages, members=members)
    for plan in plans:
        _attach(test_db, members[0], plan)
    private_copies = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=members[0],
    )["created_requirement_ids"]
    assert len(private_copies) == 2
    for member in members[1:]:
        for plan in plans:
            _attach(test_db, member, plan)

    counts = Counter()
    reads = projection.query_rows
    attached = shared._member_attached_plan_ids
    selected = selection.selected_plans
    schema_reads = Counter()
    columns = schema._read_columns
    tables = schema._read_table_exists

    def read_columns(conn, table):
        schema_reads[("columns", table)] += 1
        return columns(conn, table)

    def read_table(conn, table):
        schema_reads[("table", table)] += 1
        return tables(conn, table)

    def read(conn, sql, args=()):
        counts["membership_reads"] += 1
        return reads(conn, sql, args)

    def inspect(*args, **kwargs):
        counts["member_plan_inspections"] += 1
        return attached(*args, **kwargs)

    def select(*args, **kwargs):
        counts["selected_plans"] += 1
        return selected(*args, **kwargs)

    monkeypatch.setattr(projection, "query_rows", read)
    monkeypatch.setattr(shared, "_member_attached_plan_ids", inspect)
    monkeypatch.setattr(selection, "selected_plans", select)
    monkeypatch.setattr(schema, "_read_columns", read_columns)
    monkeypatch.setattr(schema, "_read_table_exists", read_table)

    def materialize(expected_selections):
        counts.clear()
        schema_reads.clear()
        started = perf_counter()
        result = materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=members[0],
        )
        print({"elapsed_ms": round((perf_counter() - started) * 1000), **counts})
        assert counts["membership_reads"] == 1
        assert counts["member_plan_inspections"] == 44
        assert counts["selected_plans"] == expected_selections
        assert schema_reads
        assert max(schema_reads.values()) == 1
        return result

    fresh = materialize(45)  # caller plus one selection per member, for both groups
    assert len(fresh["created_requirement_ids"]) == 2
    existing = materialize(1)  # no private copies remain, so no group resolution
    assert existing["created_requirement_ids"] == []
    assert existing["existing_requirement_ids"] == fresh["created_requirement_ids"]
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s", (run_id,)
        ).fetchone()[0]
        == 4
    )  # the two retired private copies remain history
    from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql

    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s "
            f"AND {unretracted_requirement_sql(test_db)}",
            (run_id,),
        ).fetchone()[0]
        == 2
    )

    # Facts do not survive an operation: the next invocation sees a new
    # attachment and gives only its attaching member a private copy.
    private = _plan(test_db, "private-materialization-probe")
    _attach(test_db, members[0], private)
    changed = materialize(1)
    assert len(changed["created_requirement_ids"]) == 1
    row = test_db.execute(
        "SELECT plan_id,deployment_member_item_id FROM qa_requirements WHERE id=%s",
        (changed["created_requirement_ids"][0],),
    ).fetchone()
    assert tuple(row) == (private, members[0])


@pytest.mark.parametrize("already_materialized", [False, True])
def test_methodless_member_obligation_keeps_shared_materialization(
    test_db, already_materialized
):
    from runtime.api.domain.test_deployment_qa_admission_execution import (
        _original_requirement,
    )
    from runtime.api.domain.test_deployment_qa_shared_plans import (
        MEMBERS,
        RUN,
        _begin,
        _materialize,
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
    prior = _materialize(test_db, MEMBERS[0]) if already_materialized else None

    result = _materialize(test_db, member)
    ids = result["created_requirement_ids"] + result["existing_requirement_ids"]
    assert len(ids) == 1
    if prior:
        assert result["created_requirement_ids"] == []
        assert ids == prior["created_requirement_ids"]
    row = test_db.execute(
        "SELECT plan_id,deployment_member_item_id FROM qa_requirements WHERE id=%s",
        (ids[0],),
    ).fetchone()
    assert tuple(row) == (plan_id, None)
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_member_item_id=%s",
            (RUN, member),
        ).fetchone()[0]
        == 0
    )
    execution = _begin(test_db, member)
    assert execution["deployment_member_item_id"] is None
    assert [row["requirement_id"] for row in execution["roster"]] == ids
