"""Real skip-polish traversal retains the workflow's QA floor."""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.fixtures.backlog_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.test_backlog import (
    _conn,
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — fixture re-export
)
from yoke_core.domain import advance_skip, advance_skip_finalize


def test_real_skip_polish_accepts_passing_verification(
    tmp_db,  # noqa: F811
) -> None:
    _seed_item(
        tmp_db,
        id=990,
        workflow_id="issue",
        status="reviewed-implementation",
        project="yoke",
    )
    conn = _conn(tmp_db)
    try:
        requirement = insert_qa_requirement(
            conn,
            item_id=990,
            qa_kind="implementation_review",
            workflow_transition_id="reviewed-implementation",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            verdict="pass",
        )
    finally:
        conn.close()

    with (
        _patch_externals(),
        mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}, clear=False),
        mock.patch.object(
            advance_skip_finalize,
            "_emit_skip_event",
            lambda *args, **kwargs: None,
        ),
        mock.patch.object(
            advance_skip_finalize,
            "_release_claim",
            lambda *args, **kwargs: {
                "released": False,
                "reason": "no_active_claim",
            },
        ),
    ):
        result = advance_skip.skip_polish(990, out=io.StringIO())

    assert result["to_status"] == "implemented"
    assert _item_field(tmp_db, 990, "status") == "implemented"
