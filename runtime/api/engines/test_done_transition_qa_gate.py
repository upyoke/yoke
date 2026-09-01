"""Real done-transition status writes retain the lifecycle QA floor."""

from __future__ import annotations

import os
from unittest import mock

from runtime.api.test_backlog import (
    _item_field,
    _patch_externals,
    _seed_claim,
    _seed_item,
    _seed_qa_requirement,
    _seed_qa_run,
    _seed_session,
    tmp_db,  # noqa: F401 — fixture re-export
)
from yoke_core.engines import done_transition


def test_update_item_direct_accepts_passing_verification(
    tmp_db,  # noqa: F811
) -> None:
    _seed_item(tmp_db, id=44, workflow_id="issue", status="implemented", project="yoke")
    _seed_session(tmp_db, session_id="sess-1")
    _seed_claim(tmp_db, session_id="sess-1", item_id="44")
    requirement_id = _seed_qa_requirement(
        tmp_db,
        item_id=44,
        qa_kind="implementation_review",
        method_id="command-ci",
    )
    _seed_qa_run(
        tmp_db,
        requirement_id=requirement_id,
        performed_by="command-ci",
    )

    with (
        _patch_externals(),
        mock.patch.dict(
            os.environ,
            {"YOKE_DB": tmp_db, "YOKE_SESSION_ID": "sess-1"},
            clear=False,
        ),
    ):
        rc = done_transition._update_item_direct(
            44,
            "status",
            "release",
            env_overrides={"YOKE_STATUS_SOURCE": "done-transition"},
        )

    assert rc == 0
    assert _item_field(tmp_db, 44, "status") == "release"
