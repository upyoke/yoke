"""A plan case stores the same method_config its materialized copy stores.

Authors may type an integer ready timeout; the stored plan case and every
requirement minted from it hold the one normalized form, byte for byte.
"""

from __future__ import annotations

from runtime.api.domain.machine_qa_host_test_support import _terminal_recipe
from runtime.api.domain.qa_plan_execution_test_support import TEST_ITEM_ID
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_plan_edit_test_support import _edit, _updated_at
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


def _case(timeout: float) -> dict:
    recipe = _terminal_recipe()
    recipe["execution_mode"] = "terminal-multiplexer"
    recipe["actions"] = [
        {"step": "answer", "keys": ["Enter"], "ready_text": ["Ready?"]},
        {"step": "complete"},
    ]
    recipe["actions"][0]["ready_timeout_seconds"] = timeout
    recipe["capture_checkpoints"] = ["answer", "complete"]
    return {
        "case_key": "hosted-connect",
        "position": 1,
        "method_id": "terminal-check",
        "instructions": "Connect the machine to the hosted service.",
        "expected_outcome": "Setup reaches the GitHub question.",
        "method_config": recipe,
        "host_baselines": ["fresh-host"],
        "entry_surface": "printf done",
        "required_completion": "complete",
    }


def _stored(conn, plan_id: int) -> str:
    return conn.execute(
        "SELECT method_config FROM qa_plan_cases WHERE plan_id=%s", (plan_id,)
    ).fetchone()[0]


def _copies(conn, plan_id: int) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT method_config FROM qa_requirements WHERE plan_id=%s",
            (plan_id,),
        ).fetchall()
    ]


def test_integer_timeouts_store_the_form_materialization_copies() -> None:
    with test_database() as conn:
        insert_item(conn, id=TEST_ITEM_ID, title="Run QA", workflow_id="issue")
        plan = create_plan(conn, project="yoke", slug="connect", name="Connect")
        replace_plan_cases(conn, plan_id=plan["id"], cases=[_case(180)])
        assert '"ready_timeout_seconds":180.0' in _stored(conn, plan["id"])
        _edit(
            conn,
            {**plan, "name": "Connect"},
            base_updated_at=_updated_at(conn, plan["id"]),
            name="Connect",
            description="",
            cases=[_case(45)],
        )
        stored = _stored(conn, plan["id"])
        assert '"ready_timeout_seconds":45.0' in stored
        set_project_default(
            conn, plan_id=plan["id"], workflow_id="issue", transition_id="implemented"
        )
        materialize_for_item(conn, item_id=TEST_ITEM_ID, transition_id="implemented")
        copies = _copies(conn, plan["id"])
    assert copies and all(copy == stored for copy in copies)
