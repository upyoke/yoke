"""A replay refused for a provider startup error keeps its no-verdict class."""

from contextlib import nullcontext
import json
import time
from unittest.mock import Mock

import pytest

from yoke_core.domain import qa_case_ci_run_recording as recording
from yoke_core.domain import qa_standalone_ci as standalone
from yoke_core.domain.qa_case_ci_conclusion import conclusion_from_error
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

REASON = (
    "ci_job_not_started_requires_operator: operator question filed; no re-dispatch.\n"
    "failed:ci_job_not_started\nbuild: failure: Provider refused this job"
)


@pytest.mark.parametrize(
    "message, conclusion, failure_class",
    [
        (REASON, "ci_job_not_started", "ci_job_not_started"),
        ("relay unavailable", "error", "infrastructure_transient"),
    ],
)
def test_item_ci_error_record_preserves_the_named_state(
    monkeypatch,
    message,
    conclusion,
    failure_class,
):
    finish = Mock(return_value=(41, 42))
    monkeypatch.setattr(recording, "finish", finish)
    with pytest.raises(QaCaseExecutionError, match="recorded QA run"):
        recording.fail(
            {"requirement_id": 42},
            run_id=None,
            evidence={},
            started=time.monotonic(),
            ci_run_id="",
            ci_run_source="dispatched",
            superseded_ci_run_id="",
            error=QaCaseExecutionError(message),
            actor=None,
        )
    evidence = json.loads(finish.call_args.kwargs["raw_result"])
    assert evidence["ci_conclusion"] == conclusion
    assert evidence["failure_class"] == failure_class
    assert evidence["error"] == message
    assert finish.call_args.kwargs["verdict"] == "error"


def test_standalone_ci_replay_records_provider_reason_and_no_verdict(
    tmp_path, monkeypatch
):
    sha = "a" * 40
    monkeypatch.setattr(
        standalone,
        "standalone_ci_target",
        lambda *args: (tmp_path, "acme/widgets", "ci.yml", "proof-tag", sha, {}),
    )
    monkeypatch.setattr(standalone.lane, "github_actions_authority", nullcontext)
    monkeypatch.setattr(
        standalone.lane,
        "dispatch_workflow",
        Mock(side_effect=QaCaseExecutionError(REASON)),
    )
    record = Mock(return_value=(41, 42))
    monkeypatch.setattr(standalone, "_record_run", record)
    result = standalone.execute_standalone_ci(
        {
            "requirement_id": 42,
            "standalone_execution_id": "manual-run",
            "project": "widgets",
            "method_config": {"command": "true"},
        }
    )
    assert result["failure_class"] == "ci_job_not_started"
    assert result["ci_conclusion"] == "ci_job_not_started"
    evidence = json.loads(record.call_args.kwargs["raw_result"])
    assert evidence["ci_diagnostics"] == REASON


def test_error_text_never_turns_an_execution_exception_into_a_test_verdict():
    assert conclusion_from_error(QaCaseExecutionError("failed:failure")) == "error"
