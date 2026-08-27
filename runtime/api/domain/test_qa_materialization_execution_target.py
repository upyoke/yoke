"""Fail-closed target identity for idempotent QA materialization."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    target_digest,
)
from yoke_core.domain.qa_command_plan_convergence import (
    converge_registered_command_plans,
)
from yoke_core.domain.qa_command_plan_registration import (
    ensure_registered_command_plan,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item


def _materialize_command_plan(conn, *, item_id: int) -> dict:
    insert_item(
        conn,
        id=item_id,
        title="Run targeted QA",
        workflow_id="issue",
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"targeted-plan-{item_id}",
        name="Targeted plan",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "command",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the target command.",
                "expected_outcome": "The command passes.",
                "method_config": {"command": "true"},
            }
        ],
    )
    set_project_default(
        conn,
        plan_id=int(plan["id"]),
        workflow_id="issue",
        transition_id="implemented",
    )
    return materialize_for_item(
        conn,
        item_id=item_id,
        transition_id="implemented",
    )


def test_legacy_unbound_rows_are_not_silently_reused() -> None:
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=821)
        requirement_id = result["created_requirement_ids"][0]
        conn.execute(
            "UPDATE qa_requirements SET execution_target_json=NULL,"
            "execution_target_digest=NULL WHERE id=%s",
            (requirement_id,),
        )
        conn.commit()

        with pytest.raises(
            QaPlanError,
            match="legacy QA requirement.*start a fresh",
        ):
            materialize_for_item(
                conn,
                item_id=821,
                transition_id="implemented",
            )


def test_rows_bound_to_another_target_are_not_silently_reused() -> None:
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=822)
        requirement_id = result["created_requirement_ids"][0]
        raw = conn.execute(
            "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()["execution_target_json"]
        other_target = json.loads(raw)
        other_target["environment"] = {
            "id": "yoke-api-stage",
            "name": "stage",
        }
        conn.execute(
            "UPDATE qa_requirements SET execution_target_json=%s,"
            "execution_target_digest=%s WHERE id=%s",
            (
                canonical_target(other_target),
                target_digest(other_target),
                requirement_id,
            ),
        )
        conn.commit()

        with pytest.raises(
            QaPlanError,
            match="different execution target.*start a fresh",
        ):
            materialize_for_item(
                conn,
                item_id=822,
                transition_id="implemented",
            )


def test_matching_target_rows_are_reused_idempotently() -> None:
    with test_database() as conn:
        first = _materialize_command_plan(conn, item_id=823)
        second = materialize_for_item(
            conn,
            item_id=823,
            transition_id="implemented",
        )

    assert second["created_requirement_ids"] == []
    assert second["existing_requirement_ids"] == first["created_requirement_ids"]


def test_fresh_target_bound_rows_start_a_durable_execution() -> None:
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=824)
        execution = begin_plan_execution(
            conn,
            item_id=824,
            transition_id="implemented",
            actor_id="actor-824",
            session_id="session-824",
        )

    assert execution["execution_target"]["environment"]["name"] == "development"
    assert execution["execution_target_digest"]
    assert execution["roster"][0]["requirement_id"] == (
        result["created_requirement_ids"][0]
    )


def _move_the_plan_binding(conn, requirement_id: int) -> str:
    """Rewrite one requirement's stored target so its plan no longer names it.

    Models the real shape: the plan's environment binding moved after the
    requirement was written, so the stored copy names a host the plan no longer
    resolves to. Written through the same canonicalizer the product uses, so
    the row stays internally consistent — a moved binding, not a corrupt one.
    """
    raw = conn.execute(
        "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()["execution_target_json"]
    moved = json.loads(raw)
    moved["environment"] = {"name": "a-host-the-plan-no-longer-names"}
    conn.execute(
        "UPDATE qa_requirements SET execution_target_json=%s,"
        "execution_target_digest=%s WHERE id=%s",
        (canonical_target(moved), target_digest(moved), requirement_id),
    )
    conn.commit()
    return target_digest(moved)


def _stored_digest(conn, requirement_id: int) -> str:
    return str(conn.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()["execution_target_digest"])


def test_rematerializing_drops_a_target_the_plan_no_longer_resolves_to() -> None:
    """AC-5: the moved binding is let go of, not carried forward."""
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=825)
        requirement_id = result["created_requirement_ids"][0]
        current = _stored_digest(conn, requirement_id)
        moved = _move_the_plan_binding(conn, requirement_id)

        rematerialize_for_item(conn, item_id=825, transition_id="implemented")
        after = _stored_digest(conn, requirement_id)

    assert moved != current
    assert after == current


def test_a_requirement_with_run_evidence_keeps_its_target() -> None:
    """The evidence clause: a verdict earned against one host is not relabelled."""
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=826)
        requirement_id = result["created_requirement_ids"][0]
        moved = _move_the_plan_binding(conn, requirement_id)
        conn.execute(
            "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, "
            "verdict, case_outcome, created_at) VALUES (%s, 'tester', "
            "'plan_case', 'pass', 'passed', %s)",
            (requirement_id, iso8601_now()),
        )
        conn.commit()

        with pytest.raises(
            QaPlanError,
            match="different execution target.*start a fresh",
        ):
            rematerialize_for_item(
                conn, item_id=826, transition_id="implemented"
            )
        after = _stored_digest(conn, requirement_id)

    assert after == moved


def test_a_corrupt_target_snapshot_is_still_refused() -> None:
    """A digest that disagrees with its own JSON is corruption, not a move."""
    with test_database() as conn:
        result = _materialize_command_plan(conn, item_id=827)
        requirement_id = result["created_requirement_ids"][0]
        conn.execute(
            "UPDATE qa_requirements SET execution_target_digest=%s WHERE id=%s",
            ("0" * 64, requirement_id),
        )
        conn.commit()

        with pytest.raises(QaPlanError, match="different execution target"):
            rematerialize_for_item(
                conn, item_id=827, transition_id="implemented"
            )


def test_registered_quick_command_materializes_a_stable_project_target() -> None:
    with test_database() as conn:
        conn.execute("DELETE FROM environments WHERE project_id=1")
        conn.execute("DELETE FROM sites WHERE project_id=1")
        conn.commit()
        insert_item(conn, id=828, title="Run project QA", workflow_id="issue")
        registered = ensure_registered_command_plan(
            conn,
            project_id=1,
            project="yoke",
            scope="quick",
            command="true",
        )
        plan_target = conn.execute(
            "SELECT target_environment_id FROM qa_plans WHERE id=%s",
            (int(registered["plan_id"]),),
        ).fetchone()["target_environment_id"]
        first = materialize_for_item(
            conn,
            item_id=828,
            transition_id="reviewing-implementation",
        )
        second = materialize_for_item(
            conn,
            item_id=828,
            transition_id="reviewing-implementation",
        )
        execution = begin_plan_execution(
            conn,
            item_id=828,
            transition_id="reviewing-implementation",
            actor_id="actor-828",
            session_id="session-828",
        )

    target = execution["execution_target"]
    assert plan_target is None
    assert registered["target_mode"] == "project"
    assert target["schema"] == 3
    assert target["target_kind"] == "project"
    assert target["project"]["slug"] == "yoke"
    assert "site" not in target and "environment" not in target
    assert second["existing_requirement_ids"] == first["created_requirement_ids"]
    assert execution["execution_target_digest"] == target_digest(target)


def test_convergence_does_not_relabel_materialized_environment_evidence() -> None:
    with test_database() as conn:
        insert_item(conn, id=829, title="Preserve target evidence", workflow_id="issue")
        registered = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="quick", command="true",
        )
        environment_id = conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='development'"
        ).fetchone()["id"]
        conn.execute(
            "UPDATE qa_plans SET target_environment_id=%s WHERE id=%s",
            (environment_id, int(registered["plan_id"])),
        )
        conn.commit()
        materialized = materialize_for_item(
            conn, item_id=829, transition_id="reviewing-implementation",
        )
        requirement_id = materialized["created_requirement_ids"][0]
        before = conn.execute(
            "SELECT execution_target_json, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()

        converge_registered_command_plans(conn)
        plan_target = conn.execute(
            "SELECT target_environment_id FROM qa_plans WHERE id=%s",
            (int(registered["plan_id"]),),
        ).fetchone()["target_environment_id"]
        after = conn.execute(
            "SELECT execution_target_json, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()

    assert plan_target is None
    assert dict(after) == dict(before)
