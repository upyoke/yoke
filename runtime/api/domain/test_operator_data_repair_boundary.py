"""Steering-seat authorization, review digest and closed SQL grammar boundaries."""

from runtime.api.domain.operator_data_repair_boundary_test_support import (
    _Unclosed as _Unclosed,
)


from unittest.mock import MagicMock, patch

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.operator_data_repair import handle_repair
from yoke_core.domain.operator_data_repair import (
    RepairPlan,
    review_digest,
    validate_plan,
)
from yoke_core.domain.operator_data_repair_sql import RepairRefusal, validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "BEGIN; UPDATE documents SET body='x' WHERE id=1; COMMIT",
        "VACUUM documents",
        "TRUNCATE documents",
        "ALTER TABLE documents ADD x text",
        "DO $$ BEGIN DELETE FROM documents; END $$",
        "COPY documents FROM STDIN",
        "UPDATE documents SET body='x'",
        "DELETE FROM documents",
        "WITH removed AS (DELETE FROM others RETURNING *) UPDATE documents SET body='x' WHERE id=1",
        "UPDATE documents SET body='x' FROM others WHERE documents.id=others.id",
        "DELETE FROM documents USING others WHERE documents.id=others.id",
        "UPDATE documents SET body=(SELECT body FROM others) WHERE id=1",
        "UPDATE documents SET body=pg_read_file('/tmp/private') WHERE id=1",
        "UPDATE documents SET body=nextval('sequence')::text WHERE id=1",
        "UPDATE documents SET body=public.replace(body,'x','y') WHERE id=1",
        "UPDATE documents SET body='x'::public.custom_type WHERE id=1",
        "UPDATE documents SET body='x' WHERE id OPERATOR(public.=) 1",
        "UPDATE documents SET id=2 WHERE id=1",
        "UPDATE other SET body='x' WHERE id=1",
        "UPDATE pg_catalog.documents SET body='x' WHERE id=1",
        "UPDATE documents d SET body='x' WHERE id=1",
        "UPDATE documents SET body='x' WHERE id=1 RETURNING *",
    ],
)
def test_nontransactional_unbounded_and_side_effecting_sql_is_refused(sql):
    with pytest.raises(RepairRefusal):
        validate_sql(sql, "documents", ["id"])


def document(**overrides):
    fields = dict(
        project="alpha",
        sql="UPDATE documents SET body='new' WHERE id=1",
        table="documents",
        key_columns=["id"],
        before=[{"id": 1, "body": "old"}],
        after=[{"id": 1, "body": "new"}],
        reason="Reviewed repair",
    )
    fields.update(overrides)
    return RepairPlan(**fields)


def test_exact_review_digest_covers_sql_rows_and_reason():
    plan = document()
    digest = review_digest(plan)
    validate_plan(plan, digest)
    for changed in (
        document(reason="different"),
        document(sql=plan.sql + " "),
        document(after=[{"id": 1, "body": "other"}]),
    ):
        with pytest.raises(RepairRefusal) as refused:
            validate_plan(changed, digest)
        assert refused.value.code == "repair_review_changed"


@pytest.mark.parametrize(
    "changes",
    [
        {"before": [{"id": 1}], "after": [{"id": 1}]},
        {"after": [{"id": 2, "body": "new"}]},
        {"before": [{"id": 1, "body": "old"}, {"id": 1, "body": "old"}]},
        {"before": [{"id": 1, "body": '{"secret":"private"}'}]},
        {"before": [{"id": None, "body": "old"}]},
    ],
)
def test_incomplete_duplicate_changed_or_sensitive_row_guards_refuse(changes):
    plan = document(**changes)
    with pytest.raises(RepairRefusal):
        validate_plan(plan, review_digest(plan))


def test_semicolons_in_strings_are_not_statement_boundaries():
    stmt = validate_sql(
        "UPDATE documents SET body='x; COMMIT' WHERE id=1 -- harmless comment",
        "documents",
        ["id"],
    )
    assert "RETURNING id" in stmt.mutation
    assert stmt.changed_columns == ("body",)


def _repair_request(session):
    plan = document()
    return FunctionCallRequest(
        function="operator.data_repair.run",
        actor=ActorContext(actor_id="2", session_id=session),
        target=TargetRef(kind="global"),
        payload={"plan": plan.model_dump(), "reviewed_sha256": review_digest(plan)},
    )


@pytest.mark.parametrize(
    "session,project,code",
    [
        ("s1", 1, "repair_postgres_required"),
        ("s1", 2, "steering_seat_required"),
        ("", 1, "steering_seat_required"),
    ],
)
def test_steering_seat_on_the_document_project_authorizes_repair(
    session, project, code
):
    from runtime.api.domain.session_message_support_test_support import (
        message_connection,
    )
    from runtime.api.domain.steering_operation_authority_test_support import seat

    conn = message_connection()
    seat(conn, project=project)
    with (
        patch(
            "yoke_core.domain.handlers.operator_data_repair.db_helpers.connect",
            return_value=_Unclosed(conn),
        ),
        patch(
            "yoke_core.domain.handlers.operator_data_repair.require_control_plane_permission"
        ),
    ):
        outcome = handle_repair(_repair_request(session))
    assert outcome.error.code == code
    if code == "steering_seat_required":
        assert "yoke claims steering acquire --project 1" in outcome.error.message


def test_unauthenticated_actor_is_refused_before_any_read():
    request = _repair_request("s1")
    request.actor.actor_id = "anonymous"
    with patch(
        "yoke_core.domain.handlers.operator_data_repair.db_helpers.connect"
    ) as connect:
        outcome = handle_repair(request)
    assert outcome.error.code == "operator_permission_required"
    connect.assert_not_called()


def test_seat_holder_still_requires_control_plane_permission():
    from yoke_core.domain.actor_permissions import PermissionDenied

    with (
        patch(
            "yoke_core.domain.handlers.operator_data_repair.db_helpers.connect",
            return_value=MagicMock(),
        ),
        patch(
            "yoke_core.domain.handlers.operator_data_repair.resolve_project_id",
            return_value=1,
        ),
        patch("yoke_core.domain.handlers.operator_data_repair.require_operator_seat"),
        patch(
            "yoke_core.domain.handlers.operator_data_repair.require_control_plane_permission",
            side_effect=PermissionDenied("no org grant"),
        ),
    ):
        outcome = handle_repair(_repair_request("s1"))
    assert outcome.error.code == "operator_permission_required"


def test_registration_declares_floor_and_handler_owned_seat_gate():
    from yoke_core.domain.handlers import _register_operator_data_repair

    registry = MagicMock()
    _register_operator_data_repair.register(registry)
    kwargs = registry.register.call_args.kwargs
    assert kwargs["minimum_serving_version"] == "next-release"
    assert kwargs["claim_required_kind"] is None
    assert kwargs["ambient_session_required"] is False
    assert "steering_seat_required" in kwargs["guardrails"]


def test_cli_dispatches_reviewed_document_without_project_or_lane_context(tmp_path):
    import json
    from yoke_cli.commands.adapters.operator_data_repair import operator_data_repair

    plan = document()
    content = tmp_path / "repair.json"
    content.write_text(json.dumps(plan.model_dump()), encoding="utf-8")
    with patch(
        "yoke_cli.commands.adapters.operator_data_repair.dispatch_and_emit",
        return_value=0,
    ) as dispatch:
        assert (
            operator_data_repair(
                [
                    "--content-file",
                    str(content),
                    "--reviewed-sha256",
                    review_digest(plan),
                    "--dry-run",
                ]
            )
            == 0
        )
    call = dispatch.call_args.kwargs
    assert call["target"].kind == "global"
    assert call["session_id"] is None
    assert call["payload"]["dry_run"] is True
    assert call["payload"]["plan"] == plan.model_dump()
