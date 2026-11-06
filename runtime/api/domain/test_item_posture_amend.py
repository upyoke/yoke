"""Amending a filed workflow-posture selection without re-filing the item."""

from __future__ import annotations

from runtime.api.domain.item_posture_amend_test_support import (
    REVIEW as REVIEW,
    _dash as _dash,
    _plan as _plan,
    _stored as _stored,
)


import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
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
)
from yoke_core.domain.workflow_definition_validation import ITEM_POSTURE_VALUES


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
        assert (
            conn.execute(
                "SELECT 1 FROM qa_plan_item_attachments WHERE item_id=%s", (item_id,)
            ).fetchone()
            is None
        )
        assert result["binding"] is None
        attach_plan_to_item(
            conn,
            item_id=item_id,
            plan_id=int(plan["id"]),
            transition_id=REVIEW,
            qa_phase="verification",
        )
        materialized = materialize_for_item(
            conn,
            item_id=item_id,
            transition_id=REVIEW,
        )
        assert len(materialized["created_requirement_ids"]) == 1


def test_selecting_post_deploy_plan_creates_no_review_attachment() -> None:
    with test_database() as conn:
        plan = _plan(conn, "amend-post-deploy")
        item_id = _dash(conn, item_id=2810, posture={})
        attach_plan_to_item(
            conn,
            item_id=item_id,
            plan_id=int(plan["id"]),
            transition_id="release",
            qa_phase="post_deploy",
        )
        result = amend_item_posture(
            conn,
            item_id=item_id,
            key="verification",
            value={"kind": "plan", "plan_id": int(plan["id"])},
            reason="select the release-bound plan",
        )
        assert result["binding"] is None
        assert not materialize_for_item(conn, item_id=item_id, transition_id=REVIEW)[
            "created_requirement_ids"
        ]
        attachments = conn.execute(
            "SELECT transition_id, qa_phase FROM qa_plan_item_attachments "
            "WHERE item_id=%s",
            (item_id,),
        ).fetchall()
        assert [(row["transition_id"], row["qa_phase"]) for row in attachments] == [
            ("release", "post_deploy"),
        ]


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
        assert attached == []


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
        assert "yoke claims path release --help" in str(excinfo.value)
        assert "--key path_claims --clear" in str(excinfo.value)
        assert "yoke say --steering" in str(excinfo.value)
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
