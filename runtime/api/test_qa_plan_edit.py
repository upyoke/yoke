"""Full-document QA plan editing and snapshot compatibility tests."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain import db_helpers
from yoke_core.domain import qa_plan_edit as qa_plan_edit_domain
from yoke_core.domain.handlers.qa_plan_edit import handle_plan_edit
from yoke_core.domain.qa_method_management import register_project_method
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_edit import QaPlanConflictError
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)


from runtime.api.qa_plan_edit_test_support import (
    _case_ids,
    _edit,
    _plan,
    _updated_at,
)


def test_edit_replaces_metadata_and_cases_in_one_cas_write() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        base = _updated_at(conn, plan["id"])
        old_case_ids = _case_ids(conn, plan["id"])
        result = _edit(
            conn,
            plan,
            base_updated_at=base,
            name="Release gate",
            description="The full release proof.",
            cases=[
                {
                    **CATALOG_CASES[0],
                    "instructions": "Run the complete registered backend suite.",
                }
            ],
        )
        stored = conn.execute(
            "SELECT name, description, success_policy_id, updated_at "
            "FROM qa_plans WHERE id=%s",
            (plan["id"],),
        ).fetchone()
        cases = conn.execute(
            "SELECT case_key, instructions FROM qa_plan_cases "
            "WHERE plan_id=%s ORDER BY position",
            (plan["id"],),
        ).fetchall()
        new_case_ids = _case_ids(conn, plan["id"])

    assert result == {
        "plan_id": plan["id"],
        "project_id": 1,
        "project": "yoke",
        "slug": "release-readiness",
        "case_count": 1,
        "updated_at": stored["updated_at"],
        "unchanged": False,
    }
    assert stored["name"] == "Release gate"
    assert stored["description"] == "The full release proof."
    assert stored["success_policy_id"] == "all-pass"
    assert str(stored["updated_at"]) != base
    assert [row["case_key"] for row in cases] == ["backend-suite"]
    assert cases[0]["instructions"].startswith("Run the complete")
    assert new_case_ids != old_case_ids


def test_identical_edit_preserves_timestamp_and_case_row_identities() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        base = _updated_at(conn, plan["id"])
        case_ids = _case_ids(conn, plan["id"])
        result = _edit(conn, plan, base_updated_at=base)

        assert _updated_at(conn, plan["id"]) == base
        assert _case_ids(conn, plan["id"]) == case_ids

    assert result["unchanged"] is True
    assert result["updated_at"] == base


def test_stale_base_refuses_even_a_coincidentally_identical_document() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        stale = _updated_at(conn, plan["id"])
        replace_plan_cases(conn, plan_id=plan["id"], cases=CATALOG_CASES)
        after_case_replace = _updated_at(conn, plan["id"])
        assert after_case_replace != stale
        with pytest.raises(QaPlanConflictError, match="changed after"):
            _edit(conn, plan, base_updated_at=stale)
        first = _edit(
            conn,
            plan,
            base_updated_at=after_case_replace,
            description="Changed once.",
        )
        with pytest.raises(QaPlanConflictError, match="changed after"):
            _edit(
                conn,
                plan,
                base_updated_at=after_case_replace,
                description="Changed once.",
            )
        stored = conn.execute(
            "SELECT description, updated_at FROM qa_plans WHERE id=%s",
            (plan["id"],),
        ).fetchone()

    assert stored["description"] == "Changed once."
    assert str(stored["updated_at"]) == first["updated_at"]


def test_v1_policy_and_project_method_scope_are_enforced() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        external_method = register_project_method(
            conn,
            project="externalwebapp",
            slug="external-command",
            name="External command",
            description="Only the external project may use this method.",
            executor_id="worktree_run",
            verdict_path="automatic",
            verdict_contract="Exit zero.",
            evidence_contract="Captured output.",
        )
        with pytest.raises(QaPlanError, match="all-pass"):
            _edit(
                conn,
                plan,
                base_updated_at=_updated_at(conn, plan["id"]),
                success_policy_id="threshold",
            )
        with pytest.raises(QaPlanError, match="all-pass"):
            replace_plan_cases(
                conn,
                plan_id=plan["id"],
                cases=[
                    {
                        **CATALOG_CASES[0],
                        "success_policy_id": "threshold",
                    }
                ],
            )
        with pytest.raises(QaPlanError, match="unavailable"):
            replace_plan_cases(
                conn,
                plan_id=plan["id"],
                cases=[
                    {
                        **CATALOG_CASES[0],
                        "method_id": external_method["id"],
                    }
                ],
            )


def test_empty_plan_cannot_attach_or_materialize() -> None:
    with test_database() as conn:
        item = insert_item(conn, id=42, workflow_id="issue")
        plan = create_plan(
            conn,
            project="yoke",
            slug="empty-plan",
            name="Empty plan",
        )
        with pytest.raises(QaPlanError, match="no cases"):
            set_project_default(
                conn,
                plan_id=plan["id"],
                workflow_id="issue",
                transition_id="release",
            )
        with pytest.raises(QaPlanError, match="no cases"):
            attach_plan_to_item(
                conn,
                plan_id=plan["id"],
                item_id=int(item["id"]),
                transition_id="release",
            )
        conn.execute(
            "INSERT INTO qa_plan_project_defaults("
            "project_id, workflow_id, transition_id, qa_phase, plan_id, "
            "attached_at"
            ") VALUES(1, 'issue', 'release', 'verification', %s, %s)",
            (plan["id"], "2026-07-27T00:00:00Z"),
        )
        conn.commit()
        with pytest.raises(QaPlanError, match="no cases"):
            materialize_for_item(
                conn,
                item_id=int(item["id"]),
                transition_id="release",
            )
        count = conn.execute(
            "SELECT COUNT(*) AS total FROM qa_requirements WHERE item_id=%s",
            (item["id"],),
        ).fetchone()["total"]

    assert count == 0


def test_materialized_plan_is_a_whole_plan_snapshot() -> None:
    with test_database() as conn:
        first_item = insert_item(conn, id=42, workflow_id="issue")
        second_item = insert_item(conn, id=43, project_sequence=43, workflow_id="issue")
        plan = create_plan(
            conn, project="yoke", slug="snapshot-plan", name="Snapshot plan"
        )
        replace_plan_cases(conn, plan_id=plan["id"], cases=[CATALOG_CASES[0]])
        set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="release",
        )
        first = materialize_for_item(
            conn,
            item_id=int(first_item["id"]),
            transition_id="release",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=CATALOG_CASES,
        )
        again = materialize_for_item(
            conn,
            item_id=int(first_item["id"]),
            transition_id="release",
        )
        fresh = materialize_for_item(
            conn,
            item_id=int(second_item["id"]),
            transition_id="release",
        )

    assert len(first["created_requirement_ids"]) == 1
    assert again["created_requirement_ids"] == []
    assert again["existing_requirement_ids"] == first["created_requirement_ids"]
    assert len(fresh["created_requirement_ids"]) == 2


def test_identical_edit_conflicts_when_writer_commits_after_document_read() -> None:
    with test_database() as conn:
        plan = _plan(conn)
        base = _updated_at(conn, plan["id"])
        read_current_cases = qa_plan_edit_domain._current_cases

        def read_then_write(active_conn, plan_id):
            current = read_current_cases(active_conn, plan_id)
            writer = db_helpers.connect()
            try:
                replace_plan_cases(
                    writer,
                    plan_id=plan_id,
                    cases=CATALOG_CASES,
                )
            finally:
                writer.close()
            return current

        with (
            patch.object(
                qa_plan_edit_domain,
                "_current_cases",
                side_effect=read_then_write,
            ),
            pytest.raises(QaPlanConflictError, match="changed while"),
        ):
            _edit(conn, plan, base_updated_at=base)

        assert _updated_at(conn, plan["id"]) != base


def test_handler_maps_conflicts_to_the_cas_field() -> None:
    request = FunctionCallRequest(
        function="qa.plan.edit",
        actor={"session_id": "qa-plan-edit-test"},
        target={"kind": "global"},
        payload={
            "project": "yoke",
            "slug": "release-readiness",
            "base_updated_at": "base-token",
            "name": "Release readiness",
            "cases": [CATALOG_CASES[0]],
        },
    )
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=nullcontext(object()),
        ),
        patch(
            "yoke_core.domain.qa_plan_edit.edit_plan",
            side_effect=QaPlanConflictError("stale plan"),
        ),
    ):
        outcome = handle_plan_edit(request)

    assert outcome.primary_success is False and outcome.error is not None
    assert outcome.error.code == "conflict"
    assert outcome.error.jsonpath == "$.payload.base_updated_at"
