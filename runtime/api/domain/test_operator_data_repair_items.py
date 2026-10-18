"""Public item snapshots repair composite keys through the guarded boundary."""

import json
from unittest.mock import patch

import pytest

from runtime.api.domain.test_operator_data_repair import execute, receipt
from runtime.api.domain.test_operator_data_repair_boundary import _Unclosed
from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.public_item_contract import public_item_request_error
from yoke_core.domain import operator_data_repair as repair
from yoke_core.domain.handlers.operator_data_repair import handle_repair
from yoke_core.domain.item_refs_schema import ensure_item_refs_view
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from yoke_core.domain.operator_data_repair_sql import RepairRefusal


SEQUENCE = 42
REF = f"YOK-{SEQUENCE}"
FOREIGN_REF = f"EXT-{SEQUENCE}"
ITEM_KEY = 1001


@pytest.fixture
def item_conn(test_db):
    conn = test_db
    ensure_migration_audit_table(conn)
    for item_key, project in ((ITEM_KEY, 1), (2001, 2)):
        insert_item(
            conn,
            id=item_key,
            title="Repair subject",
            project_id=project,
            project_sequence=SEQUENCE,
        )
    ensure_item_refs_view(conn)
    conn.execute(
        "CREATE TABLE repair_attachments (item_id integer, transition_id text, "
        "plan_id integer, note text, PRIMARY KEY (item_id, transition_id, plan_id))"
    )
    conn.execute(
        "INSERT INTO repair_attachments VALUES (%s, 'review', 7, 'old'), "
        "(%s, 'release', 7, 'unrelated'), (2001, 'review', 7, 'foreign')",
        (ITEM_KEY, ITEM_KEY),
    )
    conn.commit()
    return conn


def document(**overrides):
    row = dict(public_ref=REF, transition_id="review", plan_id=7, note="old")
    fields = dict(
        project="yoke",
        table="repair_attachments",
        key_columns=["item_id", "transition_id", "plan_id"],
        sql=f"UPDATE repair_attachments SET note='new' WHERE public_ref='{REF}' AND transition_id='review' AND plan_id=7",
        before=[row],
        after=[{**row, "note": "new"}],
        reason="Reviewed attachment repair",
    )
    fields.update(overrides)
    return repair.RepairPlan(**fields)


def request(plan, dry_run=False):
    return FunctionCallRequest(
        function="operator.data_repair.run",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id="2", session_id="repair-seat"),
        payload=dict(
            plan=plan.model_dump(),
            reviewed_sha256=repair.review_digest(plan),
            dry_run=dry_run,
        ),
    )


def notes(conn):
    return conn.execute(
        "SELECT note FROM public.repair_attachments ORDER BY item_id, transition_id"
    ).fetchall()


@pytest.mark.parametrize("dry_run", [True, False])
def test_public_document_passes_wire_guard_and_handler(item_conn, dry_run):
    plan = document()
    call = request(plan, dry_run)
    assert public_item_request_error(call) is None
    with (
        patch(
            "yoke_core.domain.handlers.operator_data_repair.db_helpers.connect",
            return_value=_Unclosed(item_conn),
        ),
        patch("yoke_core.domain.handlers.operator_data_repair.require_operator_seat"),
        patch(
            "yoke_core.domain.handlers.operator_data_repair.require_control_plane_permission"
        ),
    ):
        outcome = handle_repair(call)
    assert outcome.primary_success, outcome.error
    assert notes(item_conn) == [
        ("unrelated",),
        ("old" if dry_run else "new",),
        ("foreign",),
    ]
    audit = receipt(item_conn)
    assert audit[0] == ("test_verified" if dry_run else "completed")
    assert json.loads(audit[2])["expected_before"] == plan.before
    assert json.loads(audit[3]) == dict(
        observed_before=plan.before, observed_after=plan.after
    )


def test_composite_key_delete_simulates_then_applies(item_conn):
    plan = document(
        sql=f"DELETE FROM repair_attachments WHERE public_ref='{REF}' AND transition_id='review' AND plan_id=7",
        after=[],
    )
    execute(item_conn, plan, dry_run=True)
    assert len(notes(item_conn)) == 3
    execute(item_conn, plan)
    assert notes(item_conn) == [("unrelated",), ("foreign",)]
    assert json.loads(receipt(item_conn)[3])["observed_after"] == []


@pytest.mark.parametrize(
    "change,code",
    [
        (
            {"before": [{**document().before[0], "note": "stale"}]},
            "repair_before_changed",
        ),
        (
            {"after": [{**document().after[0], "note": "wrong"}]},
            "repair_after_mismatch",
        ),
        (
            {
                "before": [{**document().before[0], "public_ref": FOREIGN_REF}],
                "after": [],
            },
            "repair_project_scope_mismatch",
        ),
        (
            {
                "before": [
                    {**document().before[0], "public_ref": f"YOK-{SEQUENCE + 1}"}
                ],
                "after": [],
            },
            "repair_item_ref_unknown",
        ),
        (
            {"key_columns": ["plan_id", "item_id", "transition_id"]},
            "repair_primary_key_mismatch",
        ),
    ],
)
def test_ref_resolution_and_exact_row_guards_fail_with_durable_evidence(
    item_conn, change, code
):
    if change.get("after") == []:
        change = {
            **change,
            "sql": f"DELETE FROM repair_attachments WHERE public_ref='{change['before'][0]['public_ref']}'",
        }
    with pytest.raises(RepairRefusal) as refused:
        execute(item_conn, document(**change))
    assert refused.value.code == code
    assert notes(item_conn) == [("unrelated",), ("old",), ("foreign",)]
    assert receipt(item_conn)[0] == "live_apply_failed"
    assert code in receipt(item_conn)[4]


def test_extra_predicate_rows_are_reported_by_their_real_public_ref(item_conn):
    plan = document(sql="UPDATE repair_attachments SET note='new' WHERE plan_id=7")
    with pytest.raises(RepairRefusal) as refused:
        execute(item_conn, plan)
    assert refused.value.code == "repair_before_changed"
    observed = json.loads(receipt(item_conn)[3])["observed_before"]
    assert {row["public_ref"] for row in observed} == {REF, FOREIGN_REF}
    assert all("item_id" not in row for row in observed)


def test_ref_in_assigned_text_remains_text(item_conn):
    plan = document(
        sql=f"UPDATE repair_attachments SET note='{REF}' WHERE public_ref='{REF}' AND transition_id='review'",
        after=[{**document().after[0], "note": REF}],
    )
    execute(item_conn, plan)
    assert (REF,) in notes(item_conn)


@pytest.mark.parametrize(
    "changes,code",
    [
        (
            {"before": [{**document().before[0], "item_id": ITEM_KEY}]},
            "internal_item_id_forbidden",
        ),
        (
            {"before": [{**document().before[0], "public_ref": str(ITEM_KEY)}]},
            "public_item_ref_required",
        ),
        (
            {
                "sql": f"UPDATE repair_attachments SET public_ref='{FOREIGN_REF}' WHERE public_ref='{REF}'"
            },
            "repair_key_mutation",
        ),
        ({"before": document().before * 2}, "repair_row_identity_invalid"),
    ],
)
def test_invalid_snapshot_identity_refuses_before_execution(changes, code):
    plan = document(**changes)
    with pytest.raises(RepairRefusal) as refused:
        repair.validate_plan(plan, repair.review_digest(plan))
    assert refused.value.code == code


def test_raw_internal_snapshot_still_refuses_at_wire_boundary():
    plan = document(
        before=[dict(item_id=ITEM_KEY, transition_id="review", plan_id=7, note="old")]
    )
    assert public_item_request_error(request(plan)).code == "internal_item_id_forbidden"


@pytest.mark.parametrize(
    "column,wire",
    [
        ("deployment_member_item_id", "deployment_member_public_ref"),
        ("epic_id", "epic_public_ref"),
    ],
)
@pytest.mark.parametrize("dry_run", [True, False])
def test_item_column_public_ref_resolves_and_raw_item_id_refuses(
    item_conn, column, wire, dry_run
):
    raw = document(
        table="qa_requirements",
        key_columns=["id"],
        sql="UPDATE qa_requirements SET note='x' WHERE id=1",
        before=[{"id": 1, column: ITEM_KEY}],
        after=[{"id": 1, column: ITEM_KEY}],
    )
    with pytest.raises(RepairRefusal) as refused:
        repair.validate_plan(raw, repair.review_digest(raw))
    assert refused.value.code == "internal_item_id_forbidden"

    new_ref = f"YOK-{SEQUENCE + 1}"
    insert_item(
        item_conn,
        id=ITEM_KEY + 1,
        title="Replacement member",
        project_id=1,
        project_sequence=SEQUENCE + 1,
    )
    subject = (
        dict(epic_id=ITEM_KEY, task_num=1)
        if column == "epic_id"
        else dict(
            deployment_run_id="repair-run",
            deployment_stage="qa",
            deployment_member_item_id=ITEM_KEY,
        )
    )
    requirement = insert_qa_requirement(item_conn, item_id=None, **subject)
    before = {"id": int(requirement["id"]), wire: REF}
    plan = document(
        table="qa_requirements",
        key_columns=["id"],
        sql=(
            "UPDATE qa_requirements "
            f"SET {wire}='{new_ref}' "
            f"WHERE id={before['id']} AND {wire}='{REF}'"
        ),
        before=[before],
        after=[{**before, wire: new_ref}],
    )
    execute(item_conn, plan, dry_run=dry_run)
    stored = item_conn.execute(
        f"SELECT {column} FROM public.qa_requirements WHERE id=%s",
        (before["id"],),
    ).fetchone()
    assert stored[0] == (ITEM_KEY if dry_run else ITEM_KEY + 1)
    observed = json.loads(receipt(item_conn)[3])
    assert observed["observed_before"] == plan.before
    assert observed["observed_after"] == plan.after
    assert receipt(item_conn)[0] == ("test_verified" if dry_run else "completed")


def test_public_reference_changes_invalidate_operator_review():
    plan = document()
    changed = document(before=[{**plan.before[0], "public_ref": FOREIGN_REF}])
    with pytest.raises(RepairRefusal) as refused:
        repair.validate_plan(changed, repair.review_digest(plan))
    assert refused.value.code == "repair_review_changed"
