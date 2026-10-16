"""Task source review uses real requirement creation without a deploy target."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from runtime.api.domain.handlers._epic_task_review_state_test_helpers import (
    make_request,
)
from runtime.api.domain.test_qa_planless_case_execution_target import _environment
from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain.handlers import workflow_item_epic_task_review as handlers
from yoke_core.domain.qa_requirements import cmd_requirement_add


@pytest.fixture
def review_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_test_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            insert_item(
                conn,
                id=42,
                title="Source review",
                workflow_id="epic",
                status="implementing",
            )
            insert_epic_task(
                conn, epic_id=42, task_num=1, title="Committed task", status="planning"
            )
            _environment(conn, name="local")

            @contextmanager
            def opened():
                yield conn

            with (
                patch.object(handlers, "_open_connection", opened),
                patch(
                    "yoke_core.domain.qa_requirements.connect",
                    side_effect=lambda **_: connect_test_db(db_path),
                ),
            ):
                yield conn
        finally:
            conn.close()


def test_registered_review_seed_creates_untargeted_blocking_requirement(review_db):
    request = make_request("workflow_item.epic_task.review_seed")
    outcome = handlers.handle_review_seed(request)
    assert outcome.primary_success, outcome.error
    row = review_db.execute(
        "SELECT * FROM qa_requirements WHERE epic_id=42 AND task_num=1"
    ).fetchone()
    assert row["qa_kind"] == "implementation_review"
    assert row["qa_phase"] == "verification"
    assert row["blocking_mode"] == "blocking"
    assert row["requirement_source"] == "explicit"
    assert row["workflow_transition_id"] == "reviewed-implementation"
    assert row["target_env"] is None
    assert row["execution_target_json"] is None
    assert row["execution_target_digest"] is None
    assert row["waived_at"] is None
    assert review_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == 0

    repeated = handlers.handle_review_seed(request)
    assert repeated.primary_success
    assert repeated.result_payload == outcome.result_payload
    assert (
        review_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE epic_id=42 AND task_num=1"
        ).fetchone()[0]
        == 1
    )


def test_environment_bound_requirement_still_refuses_missing_url(review_db, capsys):
    with pytest.raises(SystemExit) as error:
        cmd_requirement_add(
            epic_id=42,
            task_num=1,
            qa_kind="implementation_review",
            qa_phase="verification",
            target_env="local",
            workflow_transition_id="reviewed-implementation",
        )
    assert error.value.code == 2
    assert "no reviewable URL" in capsys.readouterr().err
    assert review_db.execute("SELECT COUNT(*) FROM qa_requirements").fetchone()[0] == 0


def test_review_seed_returns_real_creator_refusal_and_recovery(review_db):
    # Exercise the actual creator's workflow validation, not a fabricated exit.
    with patch(
        "yoke_core.domain.epic_review_qa.item_transition_for_gate",
        return_value="missing-transition",
    ):
        outcome = handlers.handle_review_seed(
            make_request("workflow_item.epic_task.review_seed")
        )
    assert not outcome.primary_success
    assert outcome.error.code == "downstream_failure"
    assert "implementation_review_requirement_create_failed" in outcome.error.message
    assert "missing-transition" in outcome.error.message
    assert "review-get before retrying review-seed" in outcome.error.message
    assert review_db.execute("SELECT COUNT(*) FROM qa_requirements").fetchone()[0] == 0
