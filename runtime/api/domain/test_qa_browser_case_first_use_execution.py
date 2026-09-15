"""First-use Browser QA from ordered-plan admission through to its runner."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import browser_qa
from yoke_core.domain.qa_case_execution import execute_case_context
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


TRANSITION = "reviewing-implementation"


def test_plan_execution_admits_a_browser_case_without_a_project_row(
    test_db: Any,
) -> None:
    """The ordered-plan roster admits first-use browser cases too."""
    item_id = 2613
    plan = create_plan(
        test_db, project="yoke", slug="browser-first-use", name="Browser first use"
    )
    replace_plan_cases(
        test_db,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "dashboard-renders",
                "position": 1,
                "method_id": "browser-check",
                "instructions": "Open the dashboard.",
                "expected_outcome": "The dashboard renders.",
                "method_config": {
                    "base_url": "http://localhost:3000",
                    "steps": [
                        {"action": "navigate", "route": "/dashboard"},
                        {
                            "action": "assert",
                            "target": "h1",
                            "check": "visible",
                        },
                    ],
                },
            }
        ],
    )
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        title="Render the dashboard",
        workflow_id="issue",
        status="implementing",
    )
    attach_plan_to_item(
        test_db,
        plan_id=int(plan["id"]),
        item_id=item_id,
        transition_id=TRANSITION,
    )
    materialize_for_item(test_db, item_id=item_id, transition_id=TRANSITION)

    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id=TRANSITION,
        actor_id="2",
        session_id="session-browser-first-use",
    )

    roster = execution["roster"]
    assert [case["runner_id"] for case in roster] == ["browser_substrate"]
    assert roster[0]["required_capability_kinds"] == ["browser-control"]


def test_admitted_browser_case_reaches_the_browser_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admission hands the case to the substrate that provisions itself."""
    executed: dict[str, Any] = {}

    class _Result:
        def to_json(self) -> str:
            return json.dumps({"verdict": "pass", "executed": 1, "runs": []})

    def _fake_execute_scenario(**kwargs: Any) -> Any:
        executed.update(kwargs)
        return _Result()

    monkeypatch.setattr(browser_qa, "execute_scenario", _fake_execute_scenario)

    result = execute_case_context(
        {
            "requirement_id": 4242,
            "item_id": 2614,
            "deployment_run_id": None,
            "project": "yoke",
            "project_id": 1,
            "runner_id": "browser_substrate",
            "required_capability_kinds": ["browser-control"],
            "method_config": {"base_url": "http://localhost:3000"},
        },
        base_url="http://localhost:3000",
    )

    assert result["runner_id"] == "browser_substrate"
    assert result["verdict"] == "pass"
    assert executed["requirement_id"] == 4242
    assert executed["project"] == "yoke"
