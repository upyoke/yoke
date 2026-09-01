"""Selected item verification remains enforceable without a workflow QA gate."""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.items_create import handle_item_create
from yoke_core.domain.handlers.qa_requirement_create import (
    handle_qa_requirement_add,
)
from yoke_core.domain.item_entry_surface import ITEM_ENTRY_SURFACE_ENV


def _create_request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.create",
        actor=ActorContext(session_id="optional-item-qa-create"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _requirement_request(item_id: int) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.add",
        actor=ActorContext(actor_id="1", session_id="optional-item-qa-add"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "method_id": "browser-check",
            "qa_phase": "verification",
            "instructions": "Inspect the workflow card in its actual route.",
            "expected_outcome": "The card matches its visual contract.",
            "method_config": {
                "steps": [
                    {"action": "navigate", "route": "/workflows"},
                    {"action": "assert", "target": "main", "check": "visible"},
                ],
            },
            "workflow_transition_id": "reviewing-implementation",
        },
    )


def test_plan_posture_attaches_and_materializes_at_dash_review(
    tmp_db,  # noqa: F811
    monkeypatch,
) -> None:
    from yoke_core.domain.qa_catalog_schema import (
        create_qa_catalog_tables,
        seed_builtin_qa_methods,
    )
    from yoke_core.domain.qa_plan_attachments import materialize_for_item
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

    conn = _conn(tmp_db)
    try:
        create_qa_catalog_tables(conn)
        seed_builtin_qa_methods(conn)
        plan = create_plan(
            conn,
            project="yoke",
            slug="dash-close",
            name="Dash close",
        )
        replace_plan_cases(conn, plan_id=plan["id"], cases=[CATALOG_CASES[0]])
    finally:
        conn.close()

    monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
    with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
        outcome = handle_item_create(
            _create_request(
                {
                    "title": "Fix the footer",
                    "instruction": "Correct the footer and verify every link.",
                    "workflow": "dash",
                    "project": "yoke",
                    "entry_surface": "web_form",
                    "workflow_posture": {
                        "verification": {"kind": "plan", "plan_id": plan["id"]},
                    },
                }
            )
        )

    assert outcome.primary_success is True, outcome.error
    item_id = int(outcome.result_payload["item_id"])
    conn = _conn(tmp_db)
    try:
        attachment = conn.execute(
            "SELECT plan_id, transition_id FROM qa_plan_item_attachments "
            "WHERE item_id=%s",
            (item_id,),
        ).fetchone()
        before = conn.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE item_id=%s",
            (item_id,),
        ).fetchone()[0]
        materialized = materialize_for_item(
            conn,
            item_id=item_id,
            transition_id="reviewing-implementation",
        )
    finally:
        conn.close()

    assert int(attachment["plan_id"]) == int(plan["id"])
    assert attachment["transition_id"] == "reviewing-implementation"
    assert int(before) == 0
    assert len(materialized["created_requirement_ids"]) == 1


def test_optional_item_qa_rejects_an_unselected_plan() -> None:
    from yoke_core.domain.qa_plan_attachments import attach_plan_to_item
    from yoke_core.domain.qa_plan_management import (
        QaPlanError,
        create_plan,
        replace_plan_cases,
    )

    with test_database() as conn:
        selected = create_plan(
            conn,
            project="yoke",
            slug="selected-dash-plan",
            name="Selected Dash plan",
        )
        other = create_plan(
            conn,
            project="yoke",
            slug="other-dash-plan",
            name="Other Dash plan",
        )
        for plan in (selected, other):
            replace_plan_cases(
                conn,
                plan_id=plan["id"],
                cases=[CATALOG_CASES[0]],
            )
        item = insert_item(
            conn,
            id=2410,
            workflow_id="dash",
            workflow_posture=json.dumps(
                {"verification": {"kind": "plan", "plan_id": selected["id"]}}
            ),
        )

        attach_plan_to_item(
            conn,
            item_id=int(item["id"]),
            plan_id=int(selected["id"]),
            transition_id="reviewing-implementation",
        )
        with pytest.raises(QaPlanError, match="accepts only the plan or method"):
            attach_plan_to_item(
                conn,
                item_id=int(item["id"]),
                plan_id=int(other["id"]),
                transition_id="reviewing-implementation",
            )


@pytest.mark.parametrize(
    ("posture", "accepted"),
    [
        (
            {"verification": {"kind": "ad_hoc", "method_id": "browser-check"}},
            True,
        ),
        (
            {"verification": {"kind": "ad_hoc", "method_id": "command"}},
            False,
        ),
        ({}, False),
    ],
)
def test_optional_item_qa_accepts_only_the_selected_ad_hoc_method(
    posture: dict,
    accepted: bool,
) -> None:
    with test_database() as conn:
        item_id = 2407 if accepted else 2408 + len(posture)
        insert_item(
            conn,
            id=item_id,
            workflow_id="dash",
            workflow_posture=json.dumps(posture),
        )
        outcome = handle_qa_requirement_add(_requirement_request(item_id))

    assert outcome.primary_success is accepted
    if not accepted:
        assert outcome.error.code == "payload_invalid"
        assert "accepts only the plan or method selected" in outcome.error.message
