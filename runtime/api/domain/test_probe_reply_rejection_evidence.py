"""A rejected harness probe reply leaves sanitized evidence on its QA run."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    materialize_installer_campaign,
)
from runtime.api.domain.test_baseline_probe_failure_causes import _claude_probe
from yoke_core.domain.handlers.machine_qa_case_evidence import (
    record_machine_case_result,
)
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.probe_reply_rejection_evidence import ARTIFACT_TYPE
from yoke_core.domain.qa_artifact_handle import parse_handle
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_harness.baseline_probe_failure_causes import (
    PROBE_EXIT_CODES,
    REJECTION_RECORD_MISSING,
)
from yoke_harness.ssh_mac_baseline_probes import run_baseline_probes

SECRET = "private-account@example.com"
UNANSWERED = PROBE_EXIT_CODES["probe_reply_unanswered"]


def _sealed_stdout(monkeypatch, capsys, reply: str) -> tuple[int, str]:
    """Run the real sealed Claude probe against a harness that replies ``reply``."""
    stream = "\n".join(
        json.dumps(event)
        for event in (
            {"type": "system", "subtype": "init", "session_id": SECRET},
            {"type": "result", "subtype": "success", "result": reply},
        )
    )
    monkeypatch.setattr(shutil, "which", lambda name, path=None: "/bin/claude")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=stream)
    )
    with pytest.raises(SystemExit) as exit_info:
        exec(compile(_claude_probe().argv[2], "claude-probe", "exec"), {})
    return exit_info.value.code, capsys.readouterr().out


def _probe_rows(code: int, stdout: str) -> dict:
    return run_baseline_probes(
        (_claude_probe(),),
        run_gui_command=lambda argv, timeout: SimpleNamespace(
            returncode=code, stdout=stdout, stderr=""
        ),
    ).evidence


def test_a_sealed_rejection_crosses_the_host_as_its_sanitized_record(
    monkeypatch, capsys
):
    code, stdout = _sealed_stdout(monkeypatch, capsys, "Signed in as " + SECRET)
    assert code == UNANSWERED
    assert SECRET not in stdout
    evidence = _probe_rows(code, stdout)
    row = evidence["probes"][0]
    record = row["reply_rejection"]
    assert record["rejection"] == "reply_not_exact"
    assert record["event_types"] == ["system", "result"]
    assert record["final_event"]["subtype"] == "success"
    assert record["harness_exit_code"] == 0
    assert "`reply_not_exact`" in evidence["reason"]
    assert SECRET not in json.dumps(evidence)


def test_an_accepted_sealed_reply_prints_nothing(monkeypatch, capsys):
    assert _sealed_stdout(monkeypatch, capsys, "OK") == (0, "")


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        json.dumps({"harness": "Claude", "rejection": "reply_not_exact"}),
        json.dumps(
            {
                "harness": "Claude",
                "rejection": "reply_not_exact",
                "event_count": 1,
                "event_types": [SECRET],
                "final_event": None,
                "exact_ok_reply": False,
                "tool_use": False,
                "degraded_context": False,
                "harness_exit_code": 0,
            }
        ),
    ],
)
def test_a_missing_or_unsanitized_record_teaches_the_recapture(stdout):
    evidence = _probe_rows(UNANSWERED, stdout)
    assert "reply_rejection" not in evidence["probes"][0]
    assert REJECTION_RECORD_MISSING in evidence["reason"]
    assert SECRET not in json.dumps(evidence)


def _case(test_db, item_id: int) -> dict:
    requirement_id = next(
        int(row["id"])
        for row in materialize_installer_campaign(test_db, item_id=item_id)
        if row["plan_case_key"] == "default-add-yoke-to-my-path"
    )
    return get_case_execution_context(test_db, requirement_id=requirement_id)


def _blocked_result(probe_evidence: dict) -> MachineCaseResult:
    return MachineCaseResult(
        case_outcome="blocked_on_precondition",
        verdict="blocked",
        evidence={
            "test_machine": "test-mac",
            "case_started": False,
            "starting_state_reset": {
                "baseline": "fresh-host",
                "ok": False,
                "error_code": "baseline_probe_failed",
                "evidence": {"user_equivalence": probe_evidence},
            },
        },
        error_code="starting_state_reset_failed",
    )


def _artifacts(test_db, run_id: int) -> list:
    return test_db.execute(
        "SELECT artifact_type,artifact_handle,metadata FROM qa_artifacts "
        "WHERE qa_run_id=%s ORDER BY id",
        (run_id,),
    ).fetchall()


def test_a_rejected_reply_is_an_artifact_and_reason_on_the_case_run(
    test_db, tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    code, stdout = _sealed_stdout(monkeypatch, capsys, "Hello " + SECRET)
    recorded = record_machine_case_result(
        test_db,
        case=_case(test_db, 4063),
        result=_blocked_result(_probe_rows(code, stdout)),
        duration_ms=3,
    )
    run = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs WHERE id=%s",
        (recorded["run_id"],),
    ).fetchone()
    assert run["verdict"] is None
    assert (
        "Claude real request: reply rejected at `reply_not_exact`"
        in (run["verdict_reason"])
    )
    artifacts = _artifacts(test_db, recorded["run_id"])
    assert [row["artifact_type"] for row in artifacts] == [
        "machine_evidence",
        ARTIFACT_TYPE,
    ]
    assert json.loads(artifacts[1]["metadata"])["probe"] == "Claude real request"
    stored = json.loads(
        Path(parse_handle(artifacts[1]["artifact_handle"])["path"]).read_text()
    )
    assert stored["reply_rejection"]["rejection"] == "reply_not_exact"
    assert set(stored["reply_rejection"]) >= {
        "event_types",
        "final_event",
        "exact_ok_reply",
        "tool_use",
        "degraded_context",
        "harness_exit_code",
    }
    assert SECRET not in json.dumps(stored)


def test_an_accepted_reply_adds_no_rejection_artifact(
    test_db, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    passed = {"probes": [{"name": "Claude real request", "ok": True}]}
    recorded = record_machine_case_result(
        test_db,
        case=_case(test_db, 4064),
        result=_blocked_result(passed),
        duration_ms=3,
    )
    assert [
        row["artifact_type"] for row in _artifacts(test_db, recorded["run_id"])
    ] == ["machine_evidence"]
    run = test_db.execute(
        "SELECT verdict_reason FROM qa_runs WHERE id=%s", (recorded["run_id"],)
    ).fetchone()
    assert run["verdict_reason"] is None


def test_settling_an_unreviewed_capture_keeps_its_rejection_reason(
    test_db, tmp_path: Path, monkeypatch
):
    from yoke_core.domain import qa_capture_settlement, qa_plan_review

    case = _case(test_db, 4065)
    requirement_id = int(case["requirement_id"])
    run_id = test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict_reason,"
        "case_outcome,started_at,created_at) VALUES(%s,'host_control',%s,"
        "'Claude real request: reply rejected at `reply_not_exact`',"
        "'blocked_on_precondition',now(),now()) RETURNING id",
        (requirement_id, case["qa_kind"]),
    ).fetchone()[0]
    monkeypatch.setattr(
        qa_capture_settlement,
        "result_rows",
        lambda conn, execution_id: [
            {
                "requirement_id": requirement_id,
                "result": {"verdict": None, "run_id": run_id},
            }
        ],
    )
    monkeypatch.setattr(
        qa_plan_review,
        "_execution_capture_run_id",
        lambda case, result: result["run_id"],
    )
    qa_capture_settlement.settle_unreviewed_execution_captures(
        test_db,
        {
            "id": "00000000-0000-0000-0000-000000004065",
            "roster": [{"requirement_id": requirement_id, "runner_id": "host_control"}],
        },
    )
    run = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert run["verdict"] == "error"
    assert run["verdict_reason"] == (
        f"{qa_capture_settlement.UNREVIEWED_CAPTURE_REASON}; "
        "Claude real request: reply rejected at `reply_not_exact`"
    )


def test_a_mission_whose_baseline_rejected_a_reply_names_it_on_its_run(
    test_db, tmp_path: Path, monkeypatch, capsys
):
    from runtime.api.domain.machine_qa_host_test_support import (
        configure_test_machine,
    )
    from runtime.api.domain.test_agent_mission_qa import (
        ACTOR,
        _materialize_mission,
        _request,
    )
    from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
    from yoke_core.domain.handlers.machine_qa_plan_case import (
        handle_plan_case_begin,
    )
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

    code, stdout = _sealed_stdout(monkeypatch, capsys, SECRET)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = _materialize_mission(test_db, item_id=4066)
    execution_id = str(
        begin_plan_execution(
            test_db,
            item_id=4066,
            transition_id="reviewing-implementation",
            actor_id=ACTOR.actor_id,
            session_id=ACTOR.session_id,
        )["id"]
    )
    subject = dict(
        item_id=4066,
        execution_id=execution_id,
        ordinal=0,
        requirement_id=requirement_id,
    )
    begun = handle_plan_case_begin(_request("test_machine.plan_case.begin", **subject))
    contract = begun.result_payload["execution"]
    receipt = {
        "baseline": "fresh-host",
        "ok": False,
        "error_code": "baseline_probe_failed",
        "evidence": {"user_equivalence": _probe_rows(code, stdout)},
    }
    preparation = {
        "baseline": "fresh-host",
        "ok": False,
        "error_code": "baseline_probe_failed",
        "scratch_path": "/tmp/planned-scratch",
        "evidence": {
            "baseline_outcome": {
                "name": "fresh-host",
                "state": "started",
                "receipt": receipt,
            },
            "scratch_created": False,
            "preparation_failure": {
                "phase": "baseline",
                "diagnostic": "Baseline restore did not prove the requested host state",
                "recovery": "Inspect the baseline receipt.",
            },
        },
    }
    ready = handle_agent_mission_ready(
        _request(
            "test_machine.mission.ready",
            **subject,
            payload={
                "lease_id": contract["lease_id"],
                "contract_digest": contract["contract_digest"],
                "preparation": preparation,
            },
        )
    )
    assert ready.primary_success, ready.error
    run_id = ready.result_payload["result"]["run_id"]
    run = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert run["verdict"] == "error"
    assert run["verdict_reason"].startswith(
        "Claude real request: reply rejected at `reply_not_exact`"
    )
    assert run["verdict_reason"].endswith(
        "Baseline restore did not prove the requested host state"
    )
    assert [row["artifact_type"] for row in _artifacts(test_db, run_id)] == [
        ARTIFACT_TYPE
    ]
