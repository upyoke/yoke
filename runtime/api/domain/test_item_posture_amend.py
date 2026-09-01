"""Amending a filed workflow-posture selection without re-filing the item."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_core.domain.item_posture_amend import (
    AMEND_GUARDS,
    UNDECLARED_KEYS,
    amend_item_posture,
)
from yoke_core.domain.item_posture_amend_guards import ItemPostureAmendError
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)
from yoke_core.domain.workflow_definition_validation import ITEM_POSTURE_VALUES


REVIEW = ITEM_POSTURE_VERIFICATION_TRANSITION


def _plan(conn, slug: str) -> dict:
    plan = create_plan(conn, project="yoke", slug=slug, name=slug)
    replace_plan_cases(conn, plan_id=plan["id"], cases=[CATALOG_CASES[0]])
    return plan


def _dash(conn, *, item_id: int, posture: dict, status: str = "idea") -> int:
    row = insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        status=status,
        workflow_posture=json.dumps(posture),
    )
    return int(row["id"])


def _stored(conn, item_id: int) -> dict:
    raw = conn.execute(
        "SELECT workflow_posture FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()[0]
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


def test_every_posture_key_in_the_vocabulary_declares_an_amend_guard() -> None:
    assert UNDECLARED_KEYS == []
    assert set(AMEND_GUARDS) == set(ITEM_POSTURE_VALUES)


def test_amend_selects_verification_so_attach_and_materialize_succeed() -> None:
    with test_database() as conn:
        plan = _plan(conn, "amend-selects-verification")
        item_id = _dash(conn, item_id=2801, posture={})

        with pytest.raises(QaPlanError, match="accepts only the plan or method"):
            attach_plan_to_item(
                conn,
                item_id=item_id,
                plan_id=int(plan["id"]),
                transition_id=REVIEW,
            )

        result = amend_item_posture(
            conn,
            item_id=item_id,
            key="verification",
            value={"kind": "plan", "plan_id": int(plan["id"])},
            reason="mission scheduled onto this item",
        )

        assert result["changed"] is True
        assert _stored(conn, item_id)["verification"] == {
            "kind": "plan",
            "plan_id": int(plan["id"]),
        }
        # The amendment attaches the plan itself, so materialization is
        # immediately reachable without a second attach call.
        attached = conn.execute(
            "SELECT plan_id, transition_id FROM qa_plan_item_attachments "
            "WHERE item_id=%s",
            (item_id,),
        ).fetchone()
        assert int(attached["plan_id"]) == int(plan["id"])
        assert attached["transition_id"] == REVIEW
        materialized = materialize_for_item(
            conn,
            item_id=item_id,
            transition_id=REVIEW,
        )
        assert len(materialized["created_requirement_ids"]) == 1


def test_replacing_verification_retires_the_superseded_snapshot() -> None:
    with test_database() as conn:
        first = _plan(conn, "amend-first-plan")
        second = _plan(conn, "amend-second-plan")
        item_id = _dash(
            conn,
            item_id=2802,
            posture={"verification": {"kind": "plan", "plan_id": int(first["id"])}},
        )
        attach_plan_to_item(
            conn,
            item_id=item_id,
            plan_id=int(first["id"]),
            transition_id=REVIEW,
        )
        stale = materialize_for_item(
            conn,
            item_id=item_id,
            transition_id=REVIEW,
        )["created_requirement_ids"]

        result = amend_item_posture(
            conn,
            item_id=item_id,
            key="verification",
            value={"kind": "plan", "plan_id": int(second["id"])},
            reason="the first plan was the wrong mission",
        )

        assert result["waived_requirement_ids"] == stale
        assert result["detached_plan_ids"] == [int(first["id"])]
        waived = conn.execute(
            "SELECT waived_at, waiver_source FROM qa_requirements WHERE id=%s",
            (stale[0],),
        ).fetchone()
        assert waived["waived_at"] is not None
        assert waived["waiver_source"] == "system"
        attached = conn.execute(
            "SELECT plan_id FROM qa_plan_item_attachments WHERE item_id=%s "
            "ORDER BY plan_id",
            (item_id,),
        ).fetchall()
        assert [int(row["plan_id"]) for row in attached] == [int(second["id"])]


def test_amend_refuses_over_a_recorded_run_and_names_the_recovery() -> None:
    with test_database() as conn:
        first = _plan(conn, "amend-recorded-plan")
        second = _plan(conn, "amend-replacement-plan")
        item_id = _dash(
            conn,
            item_id=2803,
            posture={"verification": {"kind": "plan", "plan_id": int(first["id"])}},
        )
        requirement = insert_qa_requirement(
            conn,
            item_id=item_id,
            plan_id=int(first["id"]),
            workflow_transition_id=REVIEW,
        )
        insert_qa_run(conn, qa_requirement_id=int(requirement["id"]))

        with pytest.raises(ItemPostureAmendError) as excinfo:
            amend_item_posture(
                conn,
                item_id=item_id,
                key="verification",
                value={"kind": "plan", "plan_id": int(second["id"])},
                reason="try to swap the plan out from under the run",
            )

        message = str(excinfo.value)
        assert "already carry a recorded run" in message
        assert "yoke qa requirement waive" in message
        assert _stored(conn, item_id)["verification"]["plan_id"] == int(first["id"])


def test_amend_refuses_a_key_the_pinned_workflow_does_not_allow() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2804, posture={})
        with pytest.raises(ItemPostureAmendError, match="does not allow posture key"):
            amend_item_posture(
                conn,
                item_id=item_id,
                key="approval",
                value=True,
                reason="approval is a Blitz key, not a Dash key",
            )


def test_amend_refuses_a_key_with_no_declared_guard(monkeypatch) -> None:
    monkeypatch.delitem(AMEND_GUARDS, "deployment")
    with test_database() as conn:
        item_id = _dash(conn, item_id=2805, posture={})
        with pytest.raises(ItemPostureAmendError, match="unamendable"):
            amend_item_posture(
                conn,
                item_id=item_id,
                key="deployment",
                value=True,
                reason="a key nobody declared a guard for",
            )


def test_amend_refuses_at_a_terminal_stage() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2806, posture={}, status="done")
        with pytest.raises(ItemPostureAmendError, match="terminal stage"):
            amend_item_posture(
                conn,
                item_id=item_id,
                key="deployment",
                value=True,
                reason="too late to matter",
            )


def test_amend_requires_a_reason() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2807, posture={})
        with pytest.raises(ItemPostureAmendError, match="non-empty reason"):
            amend_item_posture(
                conn,
                item_id=item_id,
                key="deployment",
                value=True,
                reason="   ",
            )


def test_amend_to_the_stored_selection_writes_nothing() -> None:
    with test_database() as conn:
        item_id = _dash(conn, item_id=2808, posture={"deployment": True})
        result = amend_item_posture(
            conn,
            item_id=item_id,
            key="deployment",
            value=True,
            reason="restating what is already stored",
        )
        assert result["changed"] is False
        assert result["event_id"] is None
        assert _stored(conn, item_id) == {"deployment": True}


def test_clearing_path_claims_refuses_while_its_claims_are_live() -> None:
    from yoke_core.domain.path_claims_register import register_for_item

    with test_database() as conn:
        item_id = _dash(conn, item_id=2809, posture={"path_claims": True})
        conn.execute(
            "INSERT INTO actors (id, kind, system_component, created_at) "
            "VALUES (1, 'human', NULL, NOW()) ON CONFLICT DO NOTHING"
        )
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id, executor, provider, model, workspace, project_id, "
            "offered_at, last_heartbeat, actor_id) VALUES "
            "(%s, 'codex', 'openai', 'gpt', '/tmp', 1, NOW(), NOW(), 1)",
            ("posture-amend-claims",),
        )
        register_for_item(
            conn,
            item_id=item_id,
            session_id="posture-amend-claims",
            paths=["ui/workflows.js"],
            integration_target="main",
            allow_planned=True,
        )
        with pytest.raises(ItemPostureAmendError) as excinfo:
            amend_item_posture(
                conn,
                item_id=item_id,
                key="path_claims",
                clear=True,
                reason="drop the coverage gate mid-flight",
            )
        assert "registered and non-terminal" in str(excinfo.value)
        assert _stored(conn, item_id) == {"path_claims": True}


def test_amend_is_registered_with_an_item_claim_and_a_cli_adapter() -> None:
    from yoke_cli.commands.registry_workflows import WORKFLOW_SUBCOMMAND_REGISTRY
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import lookup

    register_all_handlers()
    entry = lookup("workflows.item_posture.amend")
    assert entry.claim_required_kind == "item"
    assert entry.target_kinds == ("item",)
    assert "ItemWorkflowPostureAmended" in entry.emitted_event_names
    function_id, _ = WORKFLOW_SUBCOMMAND_REGISTRY[
        ("workflows", "item-posture", "amend")
    ]
    assert function_id == "workflows.item_posture.amend"
