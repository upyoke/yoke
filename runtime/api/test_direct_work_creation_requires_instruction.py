"""Direct-work creation refuses blank instructions before ID allocation."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.items_create import handle_item_create


@pytest.mark.parametrize("workflow", ["dash", "task"])
@pytest.mark.parametrize("instruction", [None, "", " \n\t"])
def test_registered_create_refuses_without_allocating_or_writing(
    tmp_db, workflow, instruction,  # noqa: F811
):
    payload = {
        "title": "Direct work",
        "workflow": workflow,
        "project": "yoke",
        "entry_surface": "cli",
        "execution_instructions_considered": True,
    }
    if instruction is not None:
        payload["instruction"] = instruction
    request = FunctionCallRequest(
        function="items.create",
        actor=ActorContext(session_id="blank-instruction-test"),
        target=TargetRef(kind="global"),
        payload=payload,
    )
    conn = _conn(tmp_db)
    try:
        before = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()

    with (
        _patch_externals(),
        mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
        mock.patch("yoke_core.domain.backlog_create_op._get_next_id") as next_id,
        mock.patch(
            "yoke_core.domain.backlog_create_op.allocate_project_sequence"
        ) as next_sequence,
    ):
        outcome = handle_item_create(request)

    assert outcome.primary_success is False
    assert outcome.error.code == "create_failed"
    assert "requires a nonblank instruction" in outcome.error.message
    assert "provide instruction text" in outcome.error.message
    next_id.assert_not_called()
    next_sequence.assert_not_called()
    conn = _conn(tmp_db)
    try:
        after = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()
    assert after == before
