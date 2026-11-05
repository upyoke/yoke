"""A corrected case stays answered across materialization and target takeovers."""

import random

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.test_deployment_qa_singleton_correction import _correct
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.domain.test_deployment_qa_successor_receipt import _arrive
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)
from yoke_core.domain.qa_requirement_correction_selection import (
    resolve_correction_selection,
)
from yoke_core.domain.qa_requirement_lineage import lineage_heads, rows_by_case
from yoke_core.domain.qa_requirement_replacement import declare_replacements


def _scope(run):
    return dict(
        deployment_run_id=run,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=takeover.WAITING,
    )


def _replace(conn, run, failed, label):
    plan = _plan(conn, label)
    _correct(conn, plan, label)
    replacements, scopes = resolve_correction_selection(
        conn, [{"requirement_id": failed}]
    )
    result = materialize_deployment_qa_stage(
        conn,
        **_scope(run),
        agent_plan=str(plan),
        replacement_keys={"command-smoke"},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed}),
        commit=False,
    )
    ids = result["created_requirement_ids"]
    assert len(ids) == 1
    declare_replacements(conn, replacements, materialized_requirement_ids=ids)
    conn.commit()
    return plan, ids[0]


def _heads(conn, run, plan):
    return rows_by_case(
        conn,
        run_id=run,
        stage_name=ITEM_QA_STAGE,
        member_item_id=takeover.WAITING,
        plan_id=plan,
    )


def _count(conn, run):
    return conn.execute(
        "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s", (run,)
    ).fetchone()[0]


@pytest.mark.parametrize(
    "shape", ["same-pass", "cross-pass", "chain-pass", "pending", "failed", "waived"]
)
@pytest.mark.parametrize(
    "trigger", ["materialize", "takeover", "two-takeovers", "rematerialize"]
)
def test_correction_head_survives_later_materialization(
    test_db, monkeypatch, shape, trigger
):
    cases = takeover._seed_old(test_db, run_qa=False)
    takeover._close_passed(test_db)
    root = cases[takeover.WAITING]
    plan = test_db.execute(
        "SELECT plan_id FROM qa_requirements WHERE id=%s", (root,)
    ).fetchone()[0]
    head_plan, head = plan, root
    run = takeover.OLD
    if shape == "waived":
        test_db.execute(
            "UPDATE qa_requirements SET waived_at=now(),waiver_source='operator' WHERE id=%s",
            (root,),
        )
        test_db.commit()
    else:
        record_case_verdict(test_db, root, "fail", evidence=True)
        if shape == "same-pass":
            _correct(test_db, plan)
            head = rematerialize_for_deployment_stage(test_db, **_scope(run))[
                "created_requirement_ids"
            ][0]
        else:
            head_plan, head = _replace(test_db, run, root, "correction")
        if shape == "chain-pass":
            record_case_verdict(test_db, head, "fail", evidence=True)
            head_plan, head = _replace(test_db, run, head, "second-correction")
        if shape.endswith("pass"):
            record_case_verdict(test_db, head, "pass", evidence=True)
        elif shape == "failed":
            record_case_verdict(test_db, head, "fail", evidence=True)
    before = _count(test_db, run)
    if "takeover" in trigger:
        takeover._contains(monkeypatch)
        for number in range(2 if trigger == "two-takeovers" else 1):
            successor = f"run-lineage-successor-{number}"
            monkeypatch.setattr(takeover, "OLD", run)
            monkeypatch.setattr(takeover, "NEW", successor)
            monkeypatch.setattr(takeover, "NEW_LINEAGE", str(number + 3) * 40)
            takeover._seed_new(test_db, lineage=takeover.NEW_LINEAGE)
            assert takeover._take_over(test_db) == run
            _arrive(test_db, ready=True)
            test_db.execute(
                "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
                (ITEM_QA_STAGE, successor),
            )
            test_db.commit()
            run = successor
            result = materialize_deployment_qa_stage(test_db, **_scope(run))
            assert result["created_requirement_ids"] == []
        # The accepted other member stayed behind; only this member moved.
        before -= 1
    _correct(test_db, plan, "later root edit")
    if trigger == "rematerialize":
        result = rematerialize_for_deployment_stage(
            test_db, **_scope(run), plan=str(plan)
        )
    else:
        result = materialize_deployment_qa_stage(test_db, **_scope(run))
    assert result["created_requirement_ids"] == []
    assert _count(test_db, run) == before
    assert _heads(test_db, run, plan)[("command-smoke", None)][0]["id"] == head
    # A failed foreign head is corrected on its own plan exactly once.
    if shape == "failed":
        _correct(test_db, head_plan, "later head edit")
        retry = rematerialize_for_deployment_stage(
            test_db, **_scope(run), plan=str(head_plan)
        )
        assert len(retry["created_requirement_ids"]) == 1
        again = rematerialize_for_deployment_stage(
            test_db, **_scope(run), plan=str(head_plan)
        )
        assert again["created_requirement_ids"] == []
    counting = CountingConnection(test_db)
    materialize_deployment_qa_stage(counting, **_scope(run))
    assert not any(
        sql.startswith(("INSERT INTO qa_requirements", "UPDATE qa_requirements"))
        for sql in counting.statements
    )


def test_same_key_without_link_is_a_distinct_lineage():
    rows = [
        dict(id=1, plan_id=1, plan_case_key="probe"),
        dict(id=2, plan_id=2, plan_case_key="probe"),
    ]
    assert [head["id"] for head in lineage_heads(rows, [rows[0]])] == [1]


def test_fork_head_is_newest_end_and_system_retractions_do_not_join():
    rows = [
        dict(id=1, replacement_requirement_id=2, superseded_by_requirement_id=3),
        dict(id=2, created_at="2026-01-02"),
        dict(id=3, created_at="2026-01-01"),
    ]
    assert lineage_heads(rows, [rows[0]])[0]["id"] == 2
    rows[1].update(retracted_at="now", retraction_source="system")
    assert lineage_heads(rows, [rows[0]])[0]["id"] == 3


@pytest.mark.parametrize("seed", range(40))
def test_random_correction_sequences_have_one_head_per_connected_lineage(seed):
    rng = random.Random(seed)
    rows = [dict(id=1, verdict="fail")]
    for rid in range(2, 40):
        parent = rng.choice(rows)
        field = rng.choice(
            ["replacement_requirement_id", "superseded_by_requirement_id"]
        )
        parent[field] = rid
        rows.append(dict(id=rid, verdict=rng.choice(["pass", "fail", "pending"])))
        heads = lineage_heads(rows, [rows[0]])
        # Independently walk the component and take its newest chain end.
        component = {1}
        while True:
            related = {
                int(row["id"])
                for row in rows
                if int(row["id"]) in component
                or any(
                    row.get(key) in component
                    for key in (
                        "replacement_requirement_id",
                        "superseded_by_requirement_id",
                    )
                )
            }
            related |= {
                row[key]
                for row in rows
                if row["id"] in component
                for key in (
                    "replacement_requirement_id",
                    "superseded_by_requirement_id",
                )
                if row.get(key)
            }
            if related == component:
                break
            component = related
        ends = [
            row
            for row in rows
            if row["id"] in component
            and not row.get("replacement_requirement_id")
            and not row.get("superseded_by_requirement_id")
        ]
        assert len(heads) == 1
        assert heads[0]["id"] == max(row["id"] for row in ends)
        assert [row["id"] for row in heads if row["verdict"] != "pass"] == (
            []
            if max(ends, key=lambda row: row["id"])["verdict"] == "pass"
            else [heads[0]["id"]]
        )
