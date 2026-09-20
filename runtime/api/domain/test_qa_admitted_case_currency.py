"""A running stage never certifies a case body the item has already corrected.

Admission copies an item requirement's body onto a run-bound row, so a later
correction to the item used to land on the source alone and leave the stage
executing the retracted body with nothing saying so. These cover both halves
of the answer: the amendment reaches the copy while that is still honest, and
refuses by name the moment it is not; and a copy that diverged anyway refuses
before the walk can certify against it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.qa_admitted_case_currency import (
    StaleAdmittedCaseError,
    admitted_case_divergence,
    admitted_source_requirement_id,
    annotate_admitted_currency,
    require_current_admitted_case,
)
from yoke_core.domain.qa_admitted_case_reconciliation import (
    ADMITTED_COPY_IN_FLIGHT_CODE,
    admitted_copies_in_flight,
)
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update
from yoke_core.domain.qa_requirement_pass_currency import canonical_method_config

NOW = "2026-09-19T23:49:58Z"
ITEM_ID = 7101
RUN_ID = "run-currency"
STAGE = "item-qa"

_NAVIGATE = {"action": "navigate", "route": "/diagnostics"}
RETRACTED = {
    "steps": [
        _NAVIGATE,
        {"action": "assert", "target": "#diagnostics", "check": "hidden"},
    ]
}
CORRECTED = {
    "steps": [
        _NAVIGATE,
        {"action": "wait_for", "target": "#diagnostics"},
        {"action": "assert", "target": "#diagnostics-toggle", "check": "visible"},
    ]
}

_CASE_BODY: dict[str, Any] = {
    "method_id": "browser-check",
    "method_name": "Browser inspection",
    "runner_id": "browser_substrate",
    "verdict_path": "agent",
    "instructions": "walk the diagnostics group",
    "expected_outcome": "the group toggles",
}


def _seed(conn: Any, *, run_status: str = "executing") -> tuple[int, int]:
    """One item requirement and the admitted copy a stage froze from it."""
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=101,
        workflow_id="dash",
        status="implementing",
    )
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version) VALUES "
        "('flow-currency',1,'Currency flow','','[]',%s,'disabled',2)",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
        "VALUES (%s,1,'flow-currency',%s,%s)",
        (RUN_ID, run_status, NOW),
    )
    conn.commit()
    source = insert_qa_requirement(
        conn,
        item_id=ITEM_ID,
        qa_kind="release_qa",
        qa_phase="post_deploy",
        method_config=json.dumps(RETRACTED),
        **_CASE_BODY,
    )
    source_id = int(source["id"])
    copy = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=RUN_ID,
        deployment_stage=STAGE,
        deployment_member_item_id=ITEM_ID,
        qa_kind="release_qa",
        qa_phase="post_deploy",
        requirement_source="flow_derived",
        plan_case_key=admitted_requirement_case_key(source_id),
        method_config=json.dumps(RETRACTED),
        **_CASE_BODY,
    )
    return source_id, int(copy["id"])


def _method_config(conn: Any, requirement_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()
    return json.loads(canonical_method_config(row["method_config"]))


def _amend(conn: Any, source_id: int) -> Any:
    return apply_requirement_update(
        conn, source_id, "method_config", json.dumps(CORRECTED)
    )


def _start_live_execution(conn: Any) -> None:
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,actor_id,session_id,roster_digest,"
        "roster_json,cursor_ordinal,state,created_at,heartbeat_at) VALUES "
        "('exec-currency',%s,%s,%s,'operator','session-currency','digest',"
        "'[]',0,'active',%s,%s)",
        (RUN_ID, STAGE, ITEM_ID, NOW, NOW),
    )
    conn.commit()


class TestAdmittedCaseKey:
    def test_reads_the_source_out_of_an_admitted_key(self) -> None:
        assert admitted_source_requirement_id("admitted-requirement-28609") == 28609

    @pytest.mark.parametrize(
        "case_key", ["ad-hoc-5", "command-smoke", "", None, "admitted-requirement-x"]
    )
    def test_every_other_case_key_names_no_source(self, case_key: Any) -> None:
        assert admitted_source_requirement_id(case_key) is None


class TestAmendmentReachesTheCopy:
    def test_unjudged_copy_on_an_executing_run_is_corrected_too(
        self, test_db: Any
    ) -> None:
        source_id, copy_id = _seed(test_db)
        result = _amend(test_db, source_id)
        assert result.ok
        assert result.admitted_copies_updated == (copy_id,)
        assert _method_config(test_db, copy_id) == CORRECTED
        assert admitted_case_divergence(test_db, copy_id) is None

    def test_a_copy_on_a_terminal_run_keeps_what_it_was_judged_against(
        self, test_db: Any
    ) -> None:
        source_id, copy_id = _seed(test_db, run_status="succeeded")
        result = _amend(test_db, source_id)
        assert result.ok
        assert result.admitted_copies_updated == ()
        assert _method_config(test_db, copy_id) == RETRACTED
        assert admitted_copies_in_flight(test_db, source_id) == []

    def test_an_item_requirement_with_no_admitted_copy_is_unchanged(
        self, test_db: Any
    ) -> None:
        insert_item(
            test_db,
            id=ITEM_ID,
            project_sequence=101,
            workflow_id="dash",
            status="implementing",
        )
        source = insert_qa_requirement(
            test_db,
            item_id=ITEM_ID,
            method_config=json.dumps(RETRACTED),
            **_CASE_BODY,
        )
        result = _amend(test_db, int(source["id"]))
        assert result.ok
        assert result.admitted_copies_updated == ()
        assert _method_config(test_db, int(source["id"])) == CORRECTED


class TestAmendmentRefusesByName:
    def test_a_copy_that_already_answered_refuses_and_writes_neither_row(
        self, test_db: Any
    ) -> None:
        source_id, copy_id = _seed(test_db)
        insert_qa_run(test_db, qa_requirement_id=copy_id, verdict="fail")
        result = _amend(test_db, source_id)
        assert not result.ok
        assert result.error_code == ADMITTED_COPY_IN_FLIGHT_CODE
        assert f"admitted case {copy_id}" in result.message
        assert RUN_ID in result.message and "supersede" in result.message
        assert _method_config(test_db, source_id) == RETRACTED
        assert _method_config(test_db, copy_id) == RETRACTED

    def test_a_copy_a_live_execution_froze_refuses_with_the_abort_recovery(
        self, test_db: Any
    ) -> None:
        source_id, copy_id = _seed(test_db)
        _start_live_execution(test_db)
        result = _amend(test_db, source_id)
        assert not result.ok
        assert result.error_code == ADMITTED_COPY_IN_FLIGHT_CODE
        assert "yoke qa plan abort" in result.message
        assert _method_config(test_db, copy_id) == RETRACTED


class TestStageRefusesASupersededBody:
    def test_a_copy_whose_source_moved_refuses_before_it_can_certify(
        self, test_db: Any
    ) -> None:
        source_id, copy_id = _seed(test_db)
        # The divergence tonight's run carried: the source corrected while
        # the copy kept the body the author had already retracted.
        test_db.execute(
            "UPDATE qa_requirements SET method_config=%s WHERE id=%s",
            (json.dumps(CORRECTED), source_id),
        )
        test_db.commit()
        divergence = admitted_case_divergence(test_db, copy_id)
        assert divergence is not None
        assert divergence.source_requirement_id == source_id
        assert divergence.fields == ("method_config",)
        with pytest.raises(StaleAdmittedCaseError) as refusal:
            require_current_admitted_case(test_db, copy_id)
        assert "admitted_case_superseded" in str(refusal.value)
        assert str(source_id) in str(refusal.value)

    def test_a_matching_copy_passes_the_check(self, test_db: Any) -> None:
        _source_id, copy_id = _seed(test_db)
        require_current_admitted_case(test_db, copy_id)

    def test_the_target_fields_admission_rewrites_are_not_divergence(
        self, test_db: Any
    ) -> None:
        source_id, copy_id = _seed(test_db)
        test_db.execute(
            "UPDATE qa_requirements SET target_env='production',"
            "qa_phase='verification' WHERE id=%s",
            (source_id,),
        )
        test_db.commit()
        assert admitted_case_divergence(test_db, copy_id) is None


class TestRunCaseListNamesCurrency:
    def test_the_run_view_says_current_or_stale_without_a_second_row(
        self, test_db: Any
    ) -> None:
        source_id, copy_id = _seed(test_db)
        rows = [{"id": copy_id, "plan_case_key": admitted_requirement_case_key(source_id)}]
        assert annotate_admitted_currency(test_db, rows)[0]["source_currency"] == (
            "current"
        )
        test_db.execute(
            "UPDATE qa_requirements SET instructions='walk it differently' WHERE id=%s",
            (source_id,),
        )
        test_db.commit()
        marked = annotate_admitted_currency(test_db, rows)[0]
        assert marked["source_currency"] == "stale"
        assert marked["source_requirement_id"] == source_id
        assert marked["source_diverging_fields"] == ["instructions"]
