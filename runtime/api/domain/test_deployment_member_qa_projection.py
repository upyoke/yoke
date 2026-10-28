"""A release displays its current obligations before a copy or attempt exists."""

import json
from collections import defaultdict

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import deployment_member_qa_projection as projection
from yoke_core.domain.deployment_member_qa_sources import definitions, identity


def run_row(run_id="run-pending", status="created"):
    return {
        "id": run_id,
        "status": status,
        "stages": json.dumps(
            [
                {
                    "name": "item-qa",
                    "stage_kind": "qa",
                    "scope": "item",
                    "target": {"kind": "persistent_environment", "environment": "prod"},
                }
            ]
        ),
    }


def member():
    return {"id": 4710, "ref": f"SAMPLE-{4710}", "project_id": 1, "project": "yoke"}


def test_pending_obligations_are_complete_and_never_borrow_source_passes():
    with test_database() as conn:
        insert_item(conn, id=4710, title="Pending member")
        ids = []
        for index in range(25):
            source = insert_qa_requirement(
                conn,
                item_id=4710,
                qa_phase="post_deploy",
                method_id="command",
                instructions=f"check {index}",
            )
            ids.append(int(source["id"]))
            insert_qa_run(conn, qa_requirement_id=int(source["id"]), verdict="pass")
        conn.commit()
        result = projection.member_qa_obligations(
            conn, [run_row()], {"run-pending": [member()]}
        )
        current = result[("run-pending", 4710)]["current"]
        assert len(current) == 25
        assert {row["source_requirement_id"] for row in current} == set(ids)
        assert all(
            row["pending_obligation"]
            and row["run_id"] is None
            and row["outcome"] == "queued"
            and not row["artifacts"]
            for row in current
        )


def test_current_sources_omit_retired_and_wrong_environment_but_keep_waivers():
    with test_database() as conn:
        insert_item(conn, id=4710, title="Scoped member")
        current = insert_qa_requirement(
            conn, item_id=4710, qa_phase="post_deploy", method_id="command"
        )
        waived = insert_qa_requirement(
            conn, item_id=4710, qa_phase="post_deploy", method_id="command"
        )
        retired = insert_qa_requirement(
            conn, item_id=4710, qa_phase="post_deploy", method_id="command"
        )
        superseded = insert_qa_requirement(
            conn, item_id=4710, qa_phase="post_deploy", method_id="command"
        )
        unrelated = insert_qa_requirement(
            conn, item_id=4710, qa_phase="verification", method_id="command"
        )
        stage = insert_qa_requirement(
            conn,
            item_id=4710,
            qa_phase="post_deploy",
            method_id="command",
            target_env="stage",
        )
        conn.execute(
            "UPDATE qa_requirements SET waived_at=created_at WHERE id=%s",
            (waived["id"],),
        )
        conn.execute(
            "UPDATE qa_requirements SET retracted_at=created_at WHERE id=%s",
            (retired["id"],),
        )
        conn.execute(
            "UPDATE qa_requirements SET superseded_by_requirement_id=%s WHERE id=%s",
            (current["id"], superseded["id"]),
        )
        conn.commit()
        result = projection.member_qa_obligations(
            conn, [run_row()], {"run-pending": [member()]}
        )
        rows = result[("run-pending", 4710)]["current"]
        assert {row["source_requirement_id"] for row in rows} == {
            current["id"],
            waived["id"],
        }
        assert next(
            row for row in rows if row["source_requirement_id"] == waived["id"]
        )["waived_at"]
        assert unrelated["id"] != stage["id"]


def test_frozen_history_does_not_read_later_source_definitions(monkeypatch):
    frozen = {
        "requirements": [
            {
                "id": 10,
                "qa_phase": "post_deploy",
                "method_id": "command",
                "instructions": "original definition",
            }
        ],
        "plans": [],
    }

    def reads(conn, sql, params):
        if "FROM deployment_run_items" in sql:
            return [
                {
                    "run_id": "run-pending",
                    "item_id": 4710,
                    "requirement_snapshot": json.dumps(frozen),
                }
            ]
        return []

    monkeypatch.setattr(projection, "query_rows", reads)
    monkeypatch.setattr(
        projection,
        "current_sources",
        lambda conn, ids: defaultdict(list) if not ids else 1 / 0,
    )
    result = projection.member_qa_obligations(
        object(), [run_row(status="succeeded")], {"run-pending": [member()]}
    )
    assert (
        result[("run-pending", 4710)]["current"][0]["instructions"]
        == "original definition"
    )


def test_source_to_copy_identity_does_not_use_titles():
    assert identity({"id": 10}) == identity(
        {"id": 40, "plan_case_key": "admitted-requirement-10"}
    )
    assert identity({"id": 10}) != identity({"id": 11})
    assert identity(
        {"plan_id": 3, "case_key": "probe", "host_baseline": "chrome"}
    ) == identity(
        {"plan_id": 3, "plan_case_key": "probe@abcdef", "host_baseline": "chrome"}
    )


def test_failed_requirement_read_is_explicit(monkeypatch):
    def fail(*args):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(projection, "current_sources", fail)
    monkeypatch.setattr(projection, "query_rows", lambda *args: [])
    result = projection.member_qa_obligations(
        object(), [run_row()], {"run-pending": [member()]}
    )
    assert "item_qa_requirements_read_failed" in result[("run-pending", 4710)]["error"]
    assert "Reload" in result[("run-pending", 4710)]["error"]


def test_frozen_plan_case_keeps_one_obligation_per_environment():
    frozen = {"id": 9, "plan_id": 3, "plan_case_key": "probe", "qa_phase": "post_deploy"}
    rows = definitions([frozen], environment_names={"stage", "prod"}, dynamic=False)
    assert {row["target_env"] for row in rows.values()} == {"stage", "prod"}
    assert len(rows) == 2


def test_unobserved_preview_target_has_a_named_reason_and_recovery(monkeypatch):
    from yoke_core.domain.deployment_member_qa_sources import stage_environments
    from yoke_core.domain import deployment_stage_receipts

    def missing(*args, **kwargs):
        raise ValueError(
            "Producer has no receipt; execute and observe the preview stage"
        )

    monkeypatch.setattr(
        deployment_stage_receipts, "deployment_stage_receipt_for_qa", missing
    )
    names, pending, error = stage_environments(
        object(),
        [
            {
                "stage_kind": "qa",
                "scope": "item",
                "target": {"kind": "run_preview", "source_stage": "preview"},
            }
        ],
        {"id": "run-preview"},
    )
    assert not names and pending
    assert "item_qa_target_pending" in error and "execute and observe" in error


def test_plan_groups_and_old_plan_copies_stay_out_of_item_cases(test_db):
    from runtime.api.domain.test_deployment_member_qa_copies import read
    from runtime.api.domain.test_deployment_qa_run_sharing import (
        MEMBERS,
        RUN,
        _form_groups,
        _seed_three,
    )

    plan_id, lone = _seed_three(test_db)
    own = insert_qa_requirement(
        test_db, item_id=MEMBERS[0], qa_phase="post_deploy", method_id="command"
    )
    # An item copy of a plan from before plan groups is history only.
    insert_qa_requirement(
        test_db, item_id=MEMBERS[0], qa_phase="post_deploy", method_id="command",
        plan_id=lone, plan_case_key="command-smoke",
    )
    test_db.commit()
    for formed in (False, True):
        if formed:
            assert _form_groups(test_db)
        projected = read(test_db, RUN, MEMBERS)
        assert [row["source_requirement_id"] for row in projected[(RUN, MEMBERS[0])]["current"]] == [
            own["id"]
        ]
        for member in MEMBERS[1:]:
            assert projected[(RUN, member)] == {"current": [], "history": []}
    assert plan_id != lone
