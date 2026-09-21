"""A delivery-target plan cannot attach before that delivery."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.item_posture_amend_guards import ItemPostureAmendError
from yoke_core.domain.item_posture_validation import validate_item_posture
from yoke_core.domain.qa_plan_attachment_validation import (
    UnreachablePlanTargetError,
)
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


ITEM_ID = 33481


def _yoke_persistent_environment(conn) -> tuple[int, str]:
    row = conn.execute(
        "SELECT e.id, e.name FROM environments e JOIN sites s ON s.id=e.site "
        "JOIN projects p ON p.id=s.project_id "
        "WHERE p.slug='yoke' ORDER BY e.id LIMIT 1"
    ).fetchone()
    assert row is not None
    return (
        int(row["id"] if hasattr(row, "keys") else row[0]),
        str(row["name"] if hasattr(row, "keys") else row[1]),
    )


def _bind_to_persistent(conn, plan_id: int) -> tuple[int, str]:
    environment_id, name = _yoke_persistent_environment(conn)
    conn.execute(
        "UPDATE qa_plans SET target_environment_id=%s WHERE id=%s",
        (environment_id, int(plan_id)),
    )
    conn.commit()
    return environment_id, name


def _pin_item_delivery(conn, item_id: int, environment_id: int) -> None:
    flow_id = f"delivery-target-{item_id}"
    conn.execute(
        "INSERT INTO deployment_flows("
        "id, project_id, name, stages, created_at, target_tier, "
        "target_environment_id, status) "
        "VALUES (%s, 1, %s, '[]', '2026-01-01T00:00:00Z', "
        "'persistent', %s, 'active')",
        (flow_id, flow_id, int(environment_id)),
    )
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s",
        (flow_id, int(item_id)),
    )
    conn.commit()


def _seed_item(conn, *, item_id: int = ITEM_ID, workflow_id: str = "issue"):
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id=workflow_id,
        status="implementing",
        workflow_posture="{}",
    )
    conn.commit()


def _bound_plan(conn, *, slug: str) -> tuple[int, int, str]:
    plan_id = create_smoke_plan(conn, project="yoke", slug=slug)
    environment_id, name = _bind_to_persistent(conn, plan_id)
    return int(plan_id), environment_id, name


@contextmanager
def _handler_uses(conn):
    class _Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def close(self):
            return None

    with patch("yoke_core.domain.db_helpers.connect", return_value=_Borrowed()):
        yield


def test_env_bound_plan_refuses_pre_delivery_verification(test_db) -> None:
    _seed_item(test_db)
    plan_id, env_id, env_name = _bound_plan(test_db, slug="prod-bound-too-early")
    _pin_item_delivery(test_db, ITEM_ID, env_id)
    with pytest.raises(UnreachablePlanTargetError, match=env_name) as caught:
        attach_plan_to_item(
            test_db,
            plan_id=plan_id,
            item_id=ITEM_ID,
            transition_id="reviewing-implementation",
        )
    message = str(caught.value)
    assert "--qa-phase post_deploy" in message
    assert "--transition release" in message
    assert "acknowledge_unreachable_target" in message


def test_env_bound_plan_still_attaches_at_post_deploy(test_db) -> None:
    _seed_item(test_db)
    plan_id, env_id, _env = _bound_plan(test_db, slug="prod-bound-post-deploy")
    _pin_item_delivery(test_db, ITEM_ID, env_id)
    result = attach_plan_to_item(
        test_db,
        plan_id=plan_id,
        item_id=ITEM_ID,
        transition_id="release",
        qa_phase="post_deploy",
    )
    assert result["qa_phase"] == "post_deploy"
    assert result["transition_id"] == "release"


def test_unbound_plan_still_attaches_before_delivery(test_db) -> None:
    _seed_item(test_db)
    plan_id = create_smoke_plan(test_db, project="yoke", slug="unbound-pre-merge")
    result = attach_plan_to_item(
        test_db,
        plan_id=int(plan_id),
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
    )
    assert result["transition_id"] == "reviewing-implementation"


def test_env_bound_plan_attaches_when_not_the_delivery_target(test_db) -> None:
    _seed_item(test_db)
    plan_id, _env_id, _name = _bound_plan(
        test_db, slug="dev-bound-not-delivery-target"
    )
    result = attach_plan_to_item(
        test_db,
        plan_id=plan_id,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
    )
    assert result["transition_id"] == "reviewing-implementation"


def test_acknowledgement_attaches_the_otherwise_refused_binding(test_db) -> None:
    _seed_item(test_db)
    plan_id, env_id, _env = _bound_plan(test_db, slug="prod-bound-acknowledged")
    _pin_item_delivery(test_db, ITEM_ID, env_id)
    result = attach_plan_to_item(
        test_db,
        plan_id=plan_id,
        item_id=ITEM_ID,
        transition_id="reviewing-implementation",
        acknowledge_unreachable_target=True,
    )
    assert result["plan_id"] == plan_id


def test_handler_names_unreachable_qa_target(test_db) -> None:
    from yoke_core.domain.handlers.qa_plan_writes import handle_item_attach

    _seed_item(test_db, item_id=33482)
    plan_id, env_id, _env = _bound_plan(test_db, slug="prod-bound-handler")
    _pin_item_delivery(test_db, 33482, env_id)
    with _handler_uses(test_db):
        outcome = handle_item_attach(
            FunctionCallRequest(
                function="qa.item_plan.attach",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="item", item_id=33482),
                payload={
                    "project": "yoke",
                    "plan_id": plan_id,
                    "transition_id": "reviewing-implementation",
                },
            )
        )
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "unreachable_qa_target"


def test_verification_posture_allows_an_environment_bound_plan(test_db) -> None:
    plan_id, _env_id, _name = _bound_plan(test_db, slug="dev-bound-posture")
    project_id = test_db.execute(
        "SELECT id FROM projects WHERE slug='yoke'"
    ).fetchone()[0]
    result = validate_item_posture(
        test_db,
        definition=builtin_workflow_runtime("dash").definition,
        project_id=int(project_id),
        posture={"verification": {"kind": "plan", "plan_id": plan_id}},
    )
    assert result["verification"]["plan_id"] == plan_id


def test_amend_refuses_when_plan_is_the_delivery_target(test_db) -> None:
    _seed_item(test_db, item_id=33484, workflow_id="dash")
    plan_id, env_id, env_name = _bound_plan(test_db, slug="prod-bound-bind")
    _pin_item_delivery(test_db, 33484, env_id)
    with pytest.raises(ItemPostureAmendError, match=env_name):
        amend_item_posture(
            test_db,
            item_id=33484,
            key="verification",
            value={"kind": "plan", "plan_id": plan_id},
            reason="select a delivery-target plan as verification",
        )


def test_existing_attachment_still_materializes(test_db) -> None:
    """An attachment that already exists keeps its meaning."""
    _seed_item(test_db, item_id=33483)
    plan_id, _env_id, _env = _bound_plan(test_db, slug="prod-bound-already-attached")
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments("
        "item_id, transition_id, qa_phase, plan_id, attached_at"
        ") VALUES (%s,'reviewing-implementation','verification',%s,"
        "'2026-09-21T00:00:00Z')",
        (33483, plan_id),
    )
    test_db.commit()
    materialized = materialize_for_item(
        test_db, item_id=33483, transition_id="reviewing-implementation"
    )
    assert materialized["created_requirement_ids"]
    assert isinstance(UnreachablePlanTargetError("x"), QaPlanError)
