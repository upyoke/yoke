"""Native refusals survive sealed execution, capture and QA without account data."""

from contextlib import redirect_stdout
import io
import json
import shutil
import subprocess
from types import SimpleNamespace

from yoke_harness.test_machine_types import HostActionResult

import pytest

from yoke_core.domain.probe_reply_rejection_evidence import (
    rejection_verdict_reason,
    reply_rejections,
)
from yoke_harness.baseline_harness_requests import harness_request
from yoke_harness.baseline_native_failures import NATIVE_FAILURES, native_failure_cause
from yoke_harness.baseline_probe_failure_causes import PROBE_EXIT_CODES
from yoke_harness.ssh_linux_baseline import capture_linux_golden
from yoke_harness.ssh_mac_baseline_probes import (
    parse_baseline_probes,
    run_baseline_probes,
)
from yoke_harness.ssh_mac_golden_capture import capture_golden_baseline
from yoke_harness.standard_baseline_probes import standard_probes

_PRIVATE = "private-account@example.com secret-token"


def _event(harness, code, message):
    if harness == "Claude":
        return json.dumps(
            {
                "type": "assistant",
                "error": code,
                "message": {"content": [{"type": "text", "text": message}]},
            }
        )
    return json.dumps(
        {
            "type": "turn.failed" if harness == "Codex" else "error",
            "error": {"code": code, "message": message},
        }
    )


@pytest.mark.parametrize("harness", ["Claude", "Codex", "Cursor"])
@pytest.mark.parametrize(
    "code,message,cause",
    [
        (
            "rate_limit",
            "You've hit your weekly limit. " + _PRIVATE,
            "probe_quota_exhausted",
        ),
        ("authentication_error", _PRIVATE, "probe_auth_rejected"),
        ("model_not_found", _PRIVATE, "probe_model_rejected"),
        ("api_connection_error", _PRIVATE, "probe_transport_failed"),
        ("rate_limit_error", _PRIVATE, "probe_rate_limited"),
        ("other", _PRIVATE, "probe_harness_exit_nonzero"),
    ],
)
def test_native_nonzero_through_sealed_probe_and_receipt(
    monkeypatch, harness, code, message, cause
):
    native = SimpleNamespace(
        returncode=7, stdout=_event(harness, code, message), stderr=""
    )
    monkeypatch.setattr(
        shutil,
        "which",
        lambda *a, **kw: (
            "/bin/" + {"Claude": "claude", "Codex": "codex", "Cursor": "agent"}[harness]
        ),
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: native)
    probe = next(
        p for p in standard_probes("linux") if p["name"] == f"{harness} real request"
    )
    stream = io.StringIO()
    with redirect_stdout(stream), pytest.raises(SystemExit) as exited:
        exec(compile(probe["argv"][2], "sealed-probe", "exec"), {})
    assert exited.value.code == PROBE_EXIT_CODES[cause]
    sealed = SimpleNamespace(
        returncode=exited.value.code, stdout=stream.getvalue(), stderr=""
    )
    result = run_baseline_probes(
        parse_baseline_probes(json.dumps({"probes": [probe]})),
        run_gui_command=lambda *a, **kw: sealed,
        classify_gui_failures=False,
    )
    assert not result.ok
    assert result.error_code == "baseline_probe_failed"
    row = result.evidence["probes"][0]
    assert row["cause"] == "probe_harness_exit_nonzero"
    if cause != "probe_harness_exit_nonzero":
        assert NATIVE_FAILURES[cause][0] in row["reason"]
    assert row["reply_rejection"]["harness_exit_code"] == 7
    assert result.evidence["recovery"] == row["recovery"]
    assert _PRIVATE not in repr(result.evidence) + sealed.stdout
    if cause != "probe_auth_rejected":
        assert "sign in" not in row["recovery"].lower()
        assert "golden-capture" not in row["recovery"]
    # A declared native request uses exactly the same diagnosis.
    declared = run_baseline_probes(
        parse_baseline_probes(
            json.dumps(
                {
                    "probes": [
                        {
                            "name": "declared request",
                            "argv": [
                                "/bin/"
                                + {
                                    "Claude": "claude",
                                    "Codex": "codex",
                                    "Cursor": "agent",
                                }[harness]
                            ],
                        }
                    ]
                }
            )
        ),
        run_gui_command=lambda *a, **kw: native,
        classify_gui_failures=False,
    )
    assert declared.evidence["probes"][0]["cause"] == "probe_harness_exit_nonzero"


@pytest.mark.parametrize("os_name", ["macos", "linux", "windows"])
def test_capture_does_not_seal_quota_failure_and_qa_retains_recovery(os_name):
    record = harness_request(["/bin/claude"]).reply_rejection(
        _event("Claude", "rate_limit", "You've hit your weekly limit"), exit_code=1
    )
    record["harness_exit_code"] = 1
    # No archive/upload/reset methods: a refused request must precede all of them.
    control = SimpleNamespace(
        check_terminal_bridge=lambda: HostActionResult(True, {}),
        os=os_name,
        run_command=lambda *a, **kw: SimpleNamespace(
            returncode=PROBE_EXIT_CODES["probe_quota_exhausted"],
            stdout=json.dumps(record),
            stderr="",
        ),
    )
    result = (
        capture_golden_baseline(control, destination="/srv/golden")
        if os_name == "macos"
        else capture_linux_golden(control, "/srv/golden", None)
    )
    assert not result.ok
    evidence = result.evidence.get("user_equivalence", result.evidence)
    assert "quota window" in evidence["recovery"]
    assert evidence["probes"][0]["cause"] == "probe_harness_exit_nonzero"
    rejections = reply_rejections(result.evidence)
    assert len(rejections) == 1
    assert "quota window" in rejections[0]["reason"]
    assert "quota window" in rejection_verdict_reason(rejections)
    assert "harness exit 1" in rejection_verdict_reason(rejections)
    assert "probe_reply_rejection artifact" in rejection_verdict_reason(rejections)


@pytest.mark.parametrize(
    "stdout,stderr,cause",
    [
        (
            '{"type":"error","error":{"type":"authentication_error"}}',
            "",
            "probe_auth_rejected",
        ),
        (
            '{"type":"result","is_error":true,"errors":["Quota exhausted"]}',
            "",
            "probe_quota_exhausted",
        ),
        ("", "ERROR: OAuth refresh failed", "probe_auth_rejected"),
        ("", "connection reset by peer", "probe_transport_failed"),
        ("", "Unknown model: private-model", "probe_model_rejected"),
        ("", "Workspace Trust Required", "cursor_workspace_trust_required"),
        ('{"type":"result","subtype":"success","result":"quota exceeded"}', "", None),
        ('{"type":"item.completed","item":{"text":"invalid api key"}}', "", None),
        (
            '{"type":"error","message":"remaining quota: 30; login model transport"}',
            "",
            None,
        ),
        ("quota report: remaining 30", "", None),
        ("", "diagnostic mentioning an expired token in documentation", None),
        ("[]\nnot json", "", None),
    ],
)
def test_only_explicit_native_error_evidence_is_classified(stdout, stderr, cause):
    assert native_failure_cause(stdout, stderr) == cause


def test_quota_wins_over_a_later_generic_rate_limit():
    stdout = _event("Claude", "rate_limit", "You've hit your weekly limit")
    stdout += "\n" + _event("Claude", "rate_limit", "request refused")
    assert native_failure_cause(stdout, "") == "probe_quota_exhausted"


def test_nonzero_with_a_valid_answer_still_has_native_exit_diagnostics():
    request = harness_request(["/bin/claude"])
    stdout = '{"type":"result","subtype":"success","result":"OK"}'
    assert request.reply_rejection(stdout) is None
    assert (
        request.reply_rejection(stdout, exit_code=7)["rejection"]
        == "native_exit_nonzero"
    )


def test_quota_diagnosis_is_durable_on_the_blocked_qa_run(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.test_probe_reply_rejection_evidence import (
        _artifacts,
        _blocked_result,
        _case,
        _probe_rows,
    )
    from yoke_core.domain.handlers.machine_qa_case_evidence import (
        record_machine_case_result,
    )
    from yoke_core.domain.qa_artifact_handle import parse_handle
    from pathlib import Path

    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    record = harness_request(["/bin/claude"]).reply_rejection(
        _event("Claude", "rate_limit", "You've hit your weekly limit " + _PRIVATE),
        exit_code=1,
    )
    record["harness_exit_code"] = 1
    evidence = _probe_rows(
        PROBE_EXIT_CODES["probe_quota_exhausted"], json.dumps(record)
    )
    recorded = record_machine_case_result(
        test_db,
        case=_case(test_db, 4102),
        result=_blocked_result(evidence),
        duration_ms=3,
    )
    run = test_db.execute(
        "SELECT verdict, verdict_reason FROM qa_runs WHERE id=%s", (recorded["run_id"],)
    ).fetchone()
    assert run["verdict"] is None
    assert "quota window" in run["verdict_reason"]
    artifact = next(
        a
        for a in _artifacts(test_db, recorded["run_id"])
        if a["artifact_type"] == "probe_reply_rejection"
    )
    stored = Path(parse_handle(artifact["artifact_handle"])["path"]).read_text()
    assert "quota window" in stored
    assert _PRIVATE not in stored + run["verdict_reason"]
