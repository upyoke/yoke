"""Execution contract for project-targeted command QA plans."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_case_execution, qa_plan_execution
from yoke_core.domain.qa_execution_environment_target import QaExecutionTargetError
from yoke_core.domain.qa_plan_execution_abort_reason import (
    UNUSABLE_BEGIN_REASON,
    abort_reason_code,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_project_execution_target import (
    resolve_execution_base_url,
)


PROJECT_TARGET = {
    "schema": 3,
    "target_kind": "project",
    "tenant": {"id": 1, "slug": "default", "name": "Default"},
    "project": {"id": 1, "slug": "yoke", "name": "Yoke"},
    "endpoints": {},
}


def _requirement(*, requires_base_url: bool = True) -> dict:
    return {
        "requirement_id": 11,
        "item_id": 42,
        "project_id": 1,
        "plan_id": 3,
        "case_key": "e2e",
        "case_position": 1,
        "baseline_position": 1,
        "host_baseline": None,
        "method_id": "command",
        "method_config": {
            "command": "python3 -m pytest tests/e2e",
            "requires_base_url": requires_base_url,
        },
        "runner_id": "worktree_run",
    }


def test_runtime_base_url_is_required_and_normalized() -> None:
    requirement = _requirement()
    with pytest.raises(ValueError, match="requires --base-url"):
        resolve_execution_base_url(PROJECT_TARGET, [requirement], "")
    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        resolve_execution_base_url(PROJECT_TARGET, [requirement], "localhost:3000")

    assert resolve_execution_base_url(
        PROJECT_TARGET,
        [requirement],
        "https://preview.example.test/",
    ) == "https://preview.example.test"


def test_ci_command_cannot_claim_a_runtime_base_url() -> None:
    requirement = {**_requirement(), "method_id": "command-ci"}
    with pytest.raises(ValueError, match="CI command cases cannot use"):
        resolve_execution_base_url(
            PROJECT_TARGET,
            [requirement],
            "https://preview.example.test",
        )


def test_environment_target_accepts_only_its_immutable_endpoints() -> None:
    target = {
        "schema": 2,
        "environment": {"name": "development"},
        "endpoints": {
            "app_url": "https://app.example.test",
            "api_url": "https://api.example.test",
        },
    }
    assert resolve_execution_base_url(target, [], "") == "https://app.example.test"
    assert resolve_execution_base_url(
        target, [], "https://api.example.test/",
    ) == "https://api.example.test"
    with pytest.raises(ValueError, match="does not belong"):
        resolve_execution_base_url(target, [], "https://other.example.test")


def test_environment_bearing_case_cannot_materialize_a_project_target() -> None:
    with test_database() as conn:
        conn.execute("DELETE FROM environments WHERE project_id=1")
        conn.execute("DELETE FROM sites WHERE project_id=1")
        conn.commit()
        insert_item(conn, id=831, title="Run browser QA", workflow_id="issue")
        plan = create_plan(conn, project="yoke", slug="browser-without-target")
        replace_plan_cases(conn, plan_id=int(plan["id"]), cases=[CATALOG_CASES[1]])
        set_project_default(
            conn,
            plan_id=int(plan["id"]),
            workflow_id="issue",
            transition_id="implemented",
        )

        with pytest.raises(
            QaExecutionTargetError,
            match="only command and command-ci",
        ):
            materialize_for_item(conn, item_id=831, transition_id="implemented")
        minted = conn.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE item_id=831"
        ).fetchone()[0]

    assert minted == 0


def test_plan_execution_passes_the_runtime_base_url_to_the_command_runner() -> None:
    calls: list[str] = []

    def dispatch(**kwargs):
        function_id = kwargs["function_id"]
        calls.append(function_id)
        if function_id == "qa.plan_execution.begin":
            return {
                "execution_id": "execution-project-target",
                "item_id": 42,
                "transition_id": "implemented",
                "state": "active",
                "roster_digest": "digest",
                "cursor_ordinal": 0,
                "execution_target": PROJECT_TARGET,
                "execution_target_digest": "target-digest",
                "requirements": [_requirement()],
                "results": [],
            }
        if function_id == "qa.plan_review.begin":
            return {"review_bundle": None}
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=dispatch,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            return_value={
                "requirement_id": 11,
                "runner_id": "worktree_run",
                "verdict": "pass",
                "case_outcome": "passed",
            },
        ) as execute,
    ):
        result = qa_plan_execution.execute_plan(
            public_ref="YOK-42",
            transition_id="implemented",
            base_url="https://preview.example.test/",
            actor=ActorContext(actor_id="7", session_id="project-target"),
        )

    assert result["state"] == "passed"
    assert result["review_status"] is None
    assert execute.call_args.kwargs["base_url"] == "https://preview.example.test"
    assert calls == [
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
        "qa.plan_review.begin",
        "qa.plan_execution.complete",
    ]


def test_capture_awaiting_independent_review_is_labelled_pending() -> None:
    """A captured case whose review bundle is open reports no verdict yet."""

    def dispatch(**kwargs):
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "execution-awaiting-review",
                "item_id": 42,
                "cursor_ordinal": 0,
                "execution_target": PROJECT_TARGET,
                "requirements": [_requirement()],
                "results": [],
            }
        if kwargs["function_id"] == "qa.plan_review.begin":
            return {"review_bundle": {"bundle_id": "bundle-1", "cases": []}}
        return {}

    captured = {"requirement_id": 11, "runner_id": "worktree_run", "verdict": None}
    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=dispatch
        ),
        mock.patch.object(
            qa_case_execution, "execute_case_context", return_value=captured
        ),
    ):
        result = qa_plan_execution.execute_plan(
            public_ref="YOK-42",
            transition_id="implemented",
            base_url="https://preview.example.test/",
            actor=ActorContext(actor_id="7", session_id="project-target"),
        )

    assert result["state"] == "awaiting_agent_review"
    assert result["review_status"] == "pending"


def test_missing_runtime_base_url_prevents_case_side_effects() -> None:
    def dispatch(**kwargs):
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "execution-project-target",
                "item_id": 42,
                "cursor_ordinal": 0,
                "execution_target": PROJECT_TARGET,
                "requirements": [_requirement()],
                "results": [],
            }
        return {}

    with (
        mock.patch.object(
            qa_plan_execution,
            "_call_plan_function",
            side_effect=dispatch,
        ),
        mock.patch.object(qa_case_execution, "execute_case_context") as execute,
        pytest.raises(qa_plan_execution.QaPlanExecutionError, match="requires --base-url"),
    ):
        qa_plan_execution.execute_plan(
            public_ref="YOK-42",
            transition_id="implemented",
            actor=ActorContext(actor_id="7", session_id="project-target"),
        )
    execute.assert_not_called()


#: The item ref the refused-run cases pass in; asserted back out of the
#: recovery recipe, so it stays one value rather than a literal per site.
REFUSED_ITEM_REF = "PREFIX-42"


def _refused_base_url_calls(abort_result: object) -> tuple[list[dict], str]:
    """Drive a plan run the immutable target refuses, and report what it did."""
    calls: list[dict] = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == "qa.plan_execution.begin":
            return {
                "execution_id": "execution-refused-base-url",
                "item_id": 42,
                "cursor_ordinal": 0,
                "execution_target": {
                    "schema": 2,
                    "environment": {"name": "production"},
                    "endpoints": {"app_url": "https://app.example.test"},
                },
                "requirements": [_requirement()],
                "results": [],
            }
        if kwargs["function_id"] == "qa.plan_execution.abort":
            if isinstance(abort_result, Exception):
                raise abort_result
            return {}
        return {}

    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=dispatch
        ),
        pytest.raises(qa_plan_execution.QaPlanExecutionError) as caught,
    ):
        qa_plan_execution.execute_plan(
            public_ref=REFUSED_ITEM_REF,
            transition_id="implemented",
            base_url="http://localhost:3000",
            actor=ActorContext(actor_id="7", session_id="refused-base-url"),
        )
    return calls, str(caught.value)


class TestRefusedRunLeavesNoActiveExecution:
    """A refusal raised after begin must not keep holding the subject.

    ``qa.plan_execution.begin`` has already persisted an ACTIVE row, so a
    base URL the immutable target disallows used to leave one that reads
    exactly like a walk somebody is driving -- blocking the deployment run's
    settlement until a holder aborted it by hand.
    """

    def test_refusal_aborts_the_execution_it_could_not_use(self) -> None:
        calls, _ = _refused_base_url_calls(abort_result=None)
        aborts = [
            call
            for call in calls
            if call["function_id"] == "qa.plan_execution.abort"
        ]
        assert len(aborts) == 1
        assert aborts[0]["payload"]["execution_id"] == "execution-refused-base-url"

    def test_abort_reason_carries_the_code_and_the_diagnosis(self) -> None:
        calls, _ = _refused_base_url_calls(abort_result=None)
        reason = next(
            call["payload"]["reason"]
            for call in calls
            if call["function_id"] == "qa.plan_execution.abort"
        )
        assert abort_reason_code(reason) == UNUSABLE_BEGIN_REASON
        assert "does not belong" in reason

    def test_refusal_says_the_subject_is_no_longer_held(self) -> None:
        _, message = _refused_base_url_calls(abort_result=None)
        assert "does not belong" in message
        assert "has been released" in message

    def test_unreleasable_execution_names_the_manual_abort(self) -> None:
        _, message = _refused_base_url_calls(
            abort_result=qa_plan_execution.QaPlanExecutionError("relay unavailable")
        )
        assert "still holds this subject" in message
        assert (
            f"yoke qa plan abort --item {REFUSED_ITEM_REF} "
            "--execution-id execution-refused-base-url" in message
        )

    def test_no_case_runs_before_the_refusal(self) -> None:
        calls, _ = _refused_base_url_calls(abort_result=None)
        assert [call["function_id"] for call in calls] == [
            "qa.plan_execution.begin",
            "qa.plan_execution.abort",
        ]
