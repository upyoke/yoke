"""The CI-run executor: verdict from the run, evidence naming the tree."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from yoke_core.domain import qa_case_ci_lane, qa_case_ci_run, qa_case_execution
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.verification_tree_binding import TreeIdentity


def _case(**overrides) -> dict:
    case = {
        "requirement_id": 41,
        "item_id": 9,
        "plan_id": 5,
        "case_key": "full",
        "method_id": "command-ci",
        "executor_id": "ci_run",
        "method_config": {
            "command": "python3 -m pytest tests/",
            "ci_workflow": "ci.yml",
            "registered_scope": "full",
        },
        "project_id": 1,
        "project": "yoke",
        "lane_branch": "PRJ-9",
    }
    case.update(overrides)
    return case


class _Recorder:
    """Captures the qa.* function calls the executor dispatches."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict]] = []

    def __call__(self, function_id, requirement_id, payload, *, actor=None):
        self.calls.append((function_id, requirement_id, payload))
        if function_id == "qa.run.add":
            return {"qa_run_id": 77}
        if function_id == "qa.artifact.add":
            return {"qa_artifact_id": 88}
        return {}

    def payload(self, function_id: str) -> dict:
        for name, _, payload in self.calls:
            if name == function_id:
                return payload
        raise AssertionError(f"{function_id} was never dispatched")


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """Stub every boundary the executor crosses, and hand back the recorder."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    artifact = tmp_path / "ci-run-output.txt"
    recorder = _Recorder()
    monkeypatch.setattr(qa_case_execution, "_dispatch", recorder)
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.check",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda tree: TreeIdentity(root=str(tree), head_sha="a" * 40),
    )
    monkeypatch.setattr(qa_case_ci_lane, "repo_slug", lambda _c: "acme/widgets")
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", lambda *a: None)
    monkeypatch.setattr(
        "yoke_core.domain.qa_artifacts.artifact_file_path",
        lambda *a, **k: artifact,
    )
    return checkout, recorder, artifact


def _run(checkout, *, dispatch, await_result, case=None, **kwargs):
    with mock.patch.object(qa_case_ci_lane, "dispatch_workflow", dispatch):
        with mock.patch.object(qa_case_ci_lane, "await_workflow", await_result):
            return qa_case_ci_run.execute_ci_case(
                case or _case(), checkout_path=checkout, **kwargs,
            )


def test_successful_run_records_a_pass_with_run_url_and_head_sha(wired):
    checkout, recorder, artifact = wired

    result = _run(
        checkout,
        dispatch=lambda **kwargs: "9182736",
        await_result=lambda **kwargs: (0, "success"),
    )

    assert result["verdict"] == "pass"
    assert result["case_outcome"] == "passed"
    assert result["executor_id"] == "ci_run"
    assert result["ci_run_id"] == "9182736"
    assert result["run_url"] == (
        "https://github.com/acme/widgets/actions/runs/9182736"
    )
    assert result["verification_tree"]["head_sha"] == "a" * 40

    added = recorder.payload("qa.run.add")
    assert added["executor_type"] == "ci_run"
    evidence = json.loads(added["raw_result"])
    assert evidence["run_url"] == result["run_url"]
    assert evidence["branch"] == "PRJ-9"
    assert evidence["workflow"] == "ci.yml"
    assert evidence["verification_tree"]["head_sha"] == "a" * 40
    assert recorder.payload("qa.run.complete")["verdict"] == "pass"


def test_failed_run_records_a_fail(wired):
    checkout, recorder, artifact = wired

    result = _run(
        checkout,
        dispatch=lambda **kwargs: "42",
        await_result=lambda **kwargs: (1, "failed: test (3.13)"),
    )

    assert result["verdict"] == "fail"
    assert result["case_outcome"] == "failed"
    assert recorder.payload("qa.run.complete")["verdict"] == "fail"
    # The captured artifact carries the poll output an operator reads.
    captured = artifact.read_text(encoding="utf-8")
    assert "failed: test (3.13)" in captured
    assert "https://github.com/acme/widgets/actions/runs/42" in captured


def test_dispatch_is_keyed_on_the_tree_under_test(wired):
    checkout, _, _ = wired
    seen: dict = {}

    def _dispatch(**kwargs):
        seen.update(kwargs)
        return "1"

    _run(checkout, dispatch=_dispatch, await_result=lambda **k: (0, "success"))

    assert seen["request_id"] == f"qa-case:41:{'a' * 40}"
    assert seen["branch"] == "PRJ-9"
    assert seen["workflow"] == "ci.yml"
    assert seen["repo"] == "acme/widgets"


def test_the_ci_budget_is_the_default_not_the_local_command_timeout(wired):
    checkout, _, _ = wired
    seen: dict = {}

    _run(
        checkout,
        dispatch=lambda **kwargs: seen.update(kwargs) or "1",
        await_result=lambda **kwargs: (0, "success"),
    )

    assert seen["timeout_seconds"] == (
        qa_case_ci_run.DEFAULT_CI_RUN_TIMEOUT_SECONDS
    )


def test_a_configured_timeout_wins_over_the_default(wired):
    checkout, _, _ = wired
    seen: dict = {}
    case = _case()
    case["method_config"]["timeout_seconds"] = 900

    _run(
        checkout,
        dispatch=lambda **kwargs: seen.update(kwargs) or "1",
        await_result=lambda **kwargs: (0, "success"),
        case=case,
    )

    assert seen["timeout_seconds"] == 900


def test_a_case_without_a_declared_workflow_fails_before_pushing(wired):
    checkout, recorder, artifact = wired
    case = _case()
    case["method_config"].pop("ci_workflow")

    with mock.patch.object(qa_case_ci_lane, "push_lane") as push:
        with pytest.raises(QaCaseExecutionError, match="ci_workflow"):
            qa_case_ci_run.execute_ci_case(case, checkout_path=checkout)

    push.assert_not_called()
    assert recorder.calls == []


def test_a_tree_binding_refusal_stops_the_gate(wired, monkeypatch):
    checkout, recorder, artifact = wired
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.check",
        lambda **kwargs: "TREE-BINDING REFUSAL: wrong tree",
    )

    with pytest.raises(QaCaseExecutionError, match="TREE-BINDING REFUSAL"):
        qa_case_ci_run.execute_ci_case(_case(), checkout_path=checkout)

    assert recorder.calls == []


def test_shared_case_execution_routes_ci_run_to_this_executor():
    with mock.patch.object(
        qa_case_ci_run, "execute_ci_case", return_value={"verdict": "pass"},
    ) as executor:
        result = qa_case_execution.execute_case_context(
            _case(), checkout_path="/tmp/tree",
        )

    assert result == {"verdict": "pass"}
    assert executor.call_args.kwargs["checkout_path"] == "/tmp/tree"
