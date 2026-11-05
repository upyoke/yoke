"""The foreground CI caller treats an ignored late verdict as successful cleanup."""

import pytest

from yoke_core.domain import qa_case_execution, qa_case_execution_cli
from yoke_core.domain import qa_case_ci_run_recording as recording


@pytest.mark.parametrize("verdict", ["pass", "fail", "error"])
def test_late_recording_prints_ignored_verdict_and_exits_zero(
    monkeypatch, tmp_path, capsys, verdict
):
    from yoke_core.domain import qa_artifacts

    monkeypatch.setattr(
        qa_artifacts, "artifact_file_path", lambda *args: tmp_path / "output.txt"
    )
    calls = []

    def dispatch(function, payload):
        calls.append((function, payload))
        return {
            "already_settled": True,
            "qa_run_id": 73,
            "verdict": "error",
            "ignored_verdict": payload.get("verdict"),
        }

    monkeypatch.setattr(
        qa_case_execution, "recording_leg", lambda *args, **kwargs: dispatch
    )
    run_id, artifact_id = recording.finish(
        {"requirement_id": 10, "project": "test", "case_key": "full-gate"},
        run_id=73,
        raw_result="{}",
        duration_ms=10,
        verdict=verdict,
        output="obsolete capture",
        actor=None,
    )
    assert artifact_id is None
    assert [name for name, _ in calls] == ["qa.artifact.add", "qa.run.complete"]
    assert calls[-1][1]["verdict"] == verdict
    result = recording.late_result(run_id, verdict)
    monkeypatch.setattr(
        qa_case_execution_cli, "execute_case", lambda *args, **kwargs: result
    )
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.build_actor",
        lambda **kwargs: None,
    )
    assert qa_case_execution_cli.run(["--requirement-id", "10"]) == 0
    output = capsys.readouterr()
    assert output.out == (
        f"QA run 73 was already settled; the late {verdict} result was not recorded\n"
    )
    assert output.err == ""


def test_failure_cleanup_also_ignores_replaced_run(monkeypatch):
    monkeypatch.setattr(recording, "finish", lambda *args, **kwargs: (73, None))
    result = recording.fail(
        {"requirement_id": 10},
        run_id=73,
        evidence={},
        started=0,
        ci_run_id="900",
        ci_run_source="adopted",
        superseded_ci_run_id="",
        error=RuntimeError("cancelled"),
        actor=None,
    )
    assert result == recording.late_result(73, "error")
