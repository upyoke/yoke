"""A running CI case replaces old passing authority before it is polled."""

import json
from unittest import mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import (
    ci_case,
    in_flight_run,
    wire_ci_case,
)
from runtime.api.domain.merge_qa_run_identity_test_support import _proof
from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain import qa_case_ci_covering_run, qa_case_ci_lane, qa_case_ci_run
from yoke_core.domain import qa_case_execution
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_run_verdict_record import update_qa_run
from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config


@pytest.mark.parametrize("adopt", [False, True])
def test_pending_ci_attempt_blocks_merge_until_same_row_passes(
    tmp_path, monkeypatch, test_db, adopt
):
    checkout, recorder, _ = wire_ci_case(tmp_path, monkeypatch)
    item = insert_item(test_db)
    case = ci_case()
    requirement = insert_qa_requirement(
        test_db,
        item_id=item["id"],
        method_id="command-ci",
        runner_id="ci_run",
        method_config=json.dumps(case["method_config"]),
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict="pass",
        started_at="2026-10-01T00:00:01Z",
        completed_at="2026-10-01T00:00:01Z",
        raw_result=stamp_executed_method_config("{}", case["method_config"]),
    )
    assert _proof(test_db, item["id"], tmp_path)[1][1] == ""
    active = []

    def dispatch(function, requirement_id, payload, **kwargs):
        result = recorder(function, requirement_id, payload, **kwargs)
        if function == "qa.run.add":
            assert payload.get("verdict") is None
            run = insert_qa_run(
                test_db,
                qa_requirement_id=requirement["id"],
                performed_by=payload["performed_by"],
                verdict=None,
                started_at="2026-10-01T00:00:02Z",
                completed_at=None,
                raw_result=payload["raw_result"],
            )
            active.append(run["id"])
            return {"qa_run_id": run["id"]}
        if function == "qa.run.complete":
            assert payload["run_id"] == active[0]
            update_qa_run(
                test_db,
                active[0],
                {
                    "verdict": payload["verdict"],
                    "raw_result": payload["raw_result"],
                    "completed_at": "2026-10-01T00:00:03Z",
                },
            )
        return result

    def poll(**kwargs):
        model, (_, refusal) = _proof(test_db, item["id"], tmp_path)
        assert "incomplete" in refusal
        assert "/actions/runs/77" in refusal
        assert model["qa_requirements"][0]["run_id"] == active[0]
        return 0, "success"

    monkeypatch.setattr(qa_case_execution, "_dispatch", dispatch)
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", lambda **k: "77")
    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", poll)
    if adopt:
        monkeypatch.setattr(
            qa_case_ci_covering_run,
            "find_run_for_tree",
            lambda **k: in_flight_run("a" * 40),
        )
    result = qa_case_ci_run.execute_ci_case(case, checkout_path=checkout)
    assert result["run_id"] == active[0]
    assert _proof(test_db, item["id"], tmp_path)[1][1] == ""
    assert [c[0] for c in recorder.calls].count("qa.run.add") == 1


@pytest.mark.parametrize(
    "failure", [RuntimeError("poll broke"), KeyboardInterrupt(), SystemExit(1)]
)
def test_error_or_interruption_completes_pending_row(tmp_path, monkeypatch, failure):
    checkout, recorder, _ = wire_ci_case(tmp_path, monkeypatch)
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", lambda **k: "42")
    with mock.patch.object(qa_case_ci_lane, "await_workflow", side_effect=failure):
        with pytest.raises(
            QaCaseExecutionError if isinstance(failure, Exception) else type(failure)
        ):
            qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)
    complete = recorder.payload("qa.run.complete")
    raw = json.loads(complete["raw_result"])
    assert complete["run_id"] == 77
    assert complete["verdict"] == "error"
    assert raw["ci_run_id"] == "42"
    assert "yoke qa case run --requirement-id" in raw["recovery"]
    assert [c[0] for c in recorder.calls].count("qa.run.add") == 1


def test_retry_settles_abandoned_attempt_and_rejoins_ci(tmp_path, monkeypatch):
    checkout, recorder, _ = wire_ci_case(tmp_path, monkeypatch)
    prior = {
        "id": 76,
        "performed_by": "ci_run",
        "verdict": None,
        "completed_at": None,
        "raw_result": json.dumps({"ci_run_id": "42"}),
    }

    def dispatch(function, requirement_id, payload, **kwargs):
        if function == "qa.run.list":
            return {"rows": [prior]}
        return recorder(function, requirement_id, payload, **kwargs)

    monkeypatch.setattr(qa_case_execution, "_dispatch", dispatch)
    monkeypatch.setattr(
        qa_case_ci_covering_run,
        "find_run_for_tree",
        lambda **k: in_flight_run("a" * 40),
    )
    monkeypatch.setattr(qa_case_ci_lane, "await_workflow", lambda **k: (0, "success"))
    result = qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)
    completions = [p for f, _, p in recorder.calls if f == "qa.run.complete"]
    assert [(p["run_id"], p["verdict"]) for p in completions] == [
        (76, "error"),
        (77, "pass"),
    ]
    abandoned = json.loads(completions[0]["raw_result"])
    assert abandoned["ci_run_id"] == "42"
    assert abandoned["replacement_ci_run_id"] == "77"
    assert result["ci_run_source"] == "attached"
