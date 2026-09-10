"""Browser plan execution preserves the durable capture-run identity."""

from yoke_core.domain import browser_qa, qa_case_execution
from yoke_core.domain.browser_qa_results import RunResult, ScenarioResult


def test_browser_case_projects_its_single_capture_run(monkeypatch):
    monkeypatch.setattr(
        browser_qa,
        "execute_scenario",
        lambda **_kwargs: ScenarioResult(
            verdict="fail",
            runs=[
                RunResult(
                    requirement_id=91,
                    qa_kind="plan_case",
                    verdict="fail",
                    qa_run_id=26575,
                )
            ],
        ),
    )
    result = qa_case_execution._browser_result(
        {"project": "yoke", "requirement_id": 91},
        base_url="https://app.example.test",
        expected_branch=None,
        expected_sha=None,
    )
    assert result["qa_run_id"] == 26575
    assert result["runs"][0]["qa_run_id"] == 26575
