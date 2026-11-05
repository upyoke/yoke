# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
