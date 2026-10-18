"""Spec intake is atomic, lossless and previewable through real creation."""

import os
from unittest import mock

import pytest

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    tmp_db,  # noqa: F401
)
from runtime.api.cli.test_task_code_project_refusal import remove_code_repository
from runtime.api.test_items_create_function import _request
from yoke_core.domain.handlers.items_create import handle_item_create
from yoke_core.domain.items import query_item


@pytest.mark.parametrize("workflow", ["issue", "epic", "dash", "task", "blitz"])
def test_spec_is_stored_in_the_create_transaction(tmp_db, workflow):  # noqa: F811
    spec = "First paragraph with `ticks` and $(literal).\n\nSecond paragraph.\n"
    if workflow == "task":
        remove_code_repository(tmp_db)
    with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
        outcome = handle_item_create(
            _request(
                {
                    "title": "Store the authored outcome",
                    "workflow": workflow,
                    "spec": spec,
                    "entry_surface": "harness_skill",
                    "execution_instructions_considered": True,
                }
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["spec_accepted"] is True
        item_id = int(outcome.result_payload["item_id"])
        assert _item_field(tmp_db, item_id, "spec") == spec
        assert spec in query_item(item_id, "body")
        assert _item_field(tmp_db, item_id, "spec_updated_at")
        assert _item_field(tmp_db, item_id, "spec_updated_by")


def test_preview_attests_acceptance_without_a_row(tmp_db):  # noqa: F811
    with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
        outcome = handle_item_create(
            _request(
                {
                    "title": "Preview the authored outcome",
                    "workflow": "issue",
                    "spec": "Do the work.\n",
                    "dry_run": True,
                }
            )
        )
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["spec_accepted"] is True
    assert outcome.result_payload["dry_run"] is True
    conn = _conn(tmp_db)
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM items WHERE title=%s",
                ("Preview the authored outcome",),
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_retired_item_text_refuses_before_creation(monkeypatch):
    called = []
    monkeypatch.setattr(
        "yoke_core.domain.backlog_create_op.execute_create",
        lambda **kw: called.append(kw),
    )
    outcome = handle_item_create(
        _request(
            {
                "title": "Legacy payload",
                "workflow": "issue",
                "instruction": "Do it.",
            }
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "item_text_field_retired"
    assert "--spec-file" in outcome.error.message
    assert not called
