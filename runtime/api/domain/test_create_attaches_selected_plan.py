"""A plan chosen when an item is filed is attached by the create itself."""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_core.domain import backlog
from yoke_core.domain.item_entry_surface import ITEM_ENTRY_SURFACE_ENV
from yoke_core.domain.qa_plan_attachments import (
    has_attached_plans,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION as REVIEW,
)

QUICK_SLUG = "registered-command-quick"


def _plan(path: str, *, with_case: bool = True) -> int:
    with _conn(path) as conn:
        plan = create_plan(conn, project="yoke", slug=QUICK_SLUG, name=QUICK_SLUG)
        if with_case:
            replace_plan_cases(conn, plan_id=plan["id"], cases=[CATALOG_CASES[0]])
        conn.commit()
        return int(plan["id"])


def _file_dash(path: str, plan_id: int, *, dry_run: bool = False) -> dict:
    with (
        _patch_externals(),
        mock.patch.dict(
            os.environ, {"YOKE_DB": path, ITEM_ENTRY_SURFACE_ENV: "harness_skill"}
        ),
    ):
        return backlog.execute_create(
            title="Dash with the project default plan",
            workflow="dash",
            project="yoke",
            entry_surface="harness_skill",
            spec="Change the thing and run the quick plan.",
            workflow_posture={"verification": {"kind": "plan", "plan_id": plan_id}},
            dry_run=dry_run,
            out=io.StringIO(),
        )


def _attachments(conn) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT item_id, plan_id, transition_id, qa_phase "
            "FROM qa_plan_item_attachments"
        ).fetchall()
    ]


def test_filed_plan_is_attached_and_materializes(tmp_db):  # noqa: F811
    plan_id = _plan(tmp_db)

    result = _file_dash(tmp_db, plan_id)

    assert result["success"] is True, result
    item_id = int(result["item_id"])
    with _conn(tmp_db) as conn:
        assert _attachments(conn) == [(item_id, plan_id, REVIEW, "verification")]
        assert has_attached_plans(conn, item_id=item_id, transition_id=REVIEW)
        materialized = materialize_for_item(
            conn, item_id=item_id, transition_id=REVIEW
        )
    assert materialized["plan_ids"] == [plan_id]
    assert materialized["created_requirement_ids"]


def test_dry_run_create_writes_no_attachment(tmp_db):  # noqa: F811
    plan_id = _plan(tmp_db)

    result = _file_dash(tmp_db, plan_id, dry_run=True)

    assert result == {"success": True, "item_id": result["item_id"], "dry_run": True}
    with _conn(tmp_db) as conn:
        assert _attachments(conn) == []


def test_refused_attach_fails_the_create_and_names_the_opt_out(tmp_db):  # noqa: F811
    plan_id = _plan(tmp_db, with_case=False)
    with _conn(tmp_db) as conn:
        before = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    result = _file_dash(tmp_db, plan_id)

    assert result["success"] is False
    assert f"verification plan {plan_id} cannot be attached" in result["error"]
    assert "--verification-method none" in result["error"]
    with _conn(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == before
        assert _attachments(conn) == []
