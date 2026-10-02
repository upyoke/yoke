"""Reset service waits and native failure evidence survive mission preparation."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import MACHINE_QA_DIAGNOSTIC_LIMIT
from yoke_contracts.systemd_service import (
    SERVICE_OPERATION_TIMEOUT_SECONDS,
    SERVICE_QUERY_TIMEOUT_SECONDS,
)
from yoke_core.domain.agent_mission_preparation import prepare_mission
from yoke_harness import ssh_linux_baseline as baseline
from yoke_harness.ssh_linux_reset_cleanup import RESET_WRITERS_PROGRAM
from yoke_harness.test_machine_types import HostActionResult


class Refused(RuntimeError):
    def __init__(self, reason, **details):
        self.receipt = {"reason": reason, **details}


def _cleanup(monkeypatch, run):
    import shutil

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/bin/systemctl" if name == "systemctl" else None,
    )
    namespace = {
        "shutil": shutil,
        "pathlib": SimpleNamespace(Path=Path),
        "home": Path("/home/tester"),
        "os": SimpleNamespace(getuid=lambda: 1001),
        "refuse": lambda reason, **details: (_ for _ in ()).throw(
            Refused(reason, **details)
        ),
    }
    # Exercise the actual bounded helper and service cleanup without process reaping.
    program = RESET_WRITERS_PROGRAM.split('if shutil.which("docker"):')[0]
    exec(program, namespace)
    return namespace


def test_service_mutations_allow_slow_stop_while_probes_keep_short_budget(monkeypatch):
    calls = []
    reloaded = False

    def run(argv, **kwargs):
        nonlocal reloaded
        calls.append((argv, kwargs["timeout"]))
        output = ""
        if "stop" in argv:
            duration = SERVICE_QUERY_TIMEOUT_SECONDS + 5
            if duration > kwargs["timeout"]:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if "daemon-reload" in argv:
            reloaded = True
        if ("list-units" in argv or "list-unit-files" in argv) and not reloaded:
            output = "com.upyoke.relay.local.service loaded active running\n"
        if argv[0] == "loginctl":
            output = "no"
        return subprocess.CompletedProcess(argv, 0, output, "")

    _cleanup(monkeypatch, run)
    mutations = {"stop", "disable", "reset-failed", "daemon-reload"}
    for argv, timeout in calls:
        expected = (
            SERVICE_OPERATION_TIMEOUT_SECONDS
            if any(v in argv for v in mutations)
            else SERVICE_QUERY_TIMEOUT_SECONDS
        )
        assert timeout == expected
    assert any("stop" in argv for argv, _ in calls)


def test_service_timeout_names_command_budget_and_unsettled_job(monkeypatch):
    def run(argv, **kwargs):
        if "stop" in argv:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        output = (
            "com.upyoke.relay.local.service loaded active running\n"
            if "list-units" in argv
            else ""
        )
        return subprocess.CompletedProcess(argv, 0, output, "")

    with pytest.raises(Refused) as caught:
        _cleanup(monkeypatch, run)
    receipt = caught.value.receipt
    assert receipt["reason"] == "linux_yoke_service_command_timeout"
    assert receipt["command"] == [
        "systemctl",
        "--user",
        "stop",
        "com.upyoke.relay.local.service",
    ]
    assert receipt["timeout_seconds"] == SERVICE_OPERATION_TIMEOUT_SECONDS
    assert "job may still be running" in receipt["recovery"]


def _failed_archive(monkeypatch, completed):
    control = SimpleNamespace(
        home="/home/tester",
        secret_values=("private-token",),
        _run=lambda *a, **k: completed,
    )
    monkeypatch.setattr(
        baseline,
        "reset_preflight",
        lambda *a: HostActionResult(True, {"preserve_claude": False}),
    )
    return baseline.archive_operation(control, "reset", "/sealed/golden")


def test_malformed_archive_receipt_keeps_bounded_redacted_transport_evidence(
    monkeypatch,
):
    result = _failed_archive(
        monkeypatch,
        subprocess.CompletedProcess(
            [], 1, "unexpected private-token " + "x" * 900, "Traceback private-token"
        ),
    )
    assert result.error_code == "linux_golden_operation_failed"
    assert result.evidence["exit_code"] == 1
    assert result.evidence["stdout"].startswith("unexpected [REDACTED]")
    assert len(result.evidence["stdout"]) <= MACHINE_QA_DIAGNOSTIC_LIMIT
    assert result.evidence["stderr"] == "Traceback [REDACTED]"
    assert "private-token" not in json.dumps(result.evidence)


def test_failed_baseline_transport_evidence_reaches_mission_without_scratch(
    monkeypatch,
):
    failed = _failed_archive(
        monkeypatch,
        subprocess.CompletedProcess(
            [], 1, "bad receipt private-token", "TimeoutExpired private-token"
        ),
    )
    failed_baseline = SimpleNamespace(
        name="fresh-host",
        ok=False,
        error_code=failed.error_code,
        evidence=failed.evidence,
    )
    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={"credential": "private-token"}),
        reach_baseline=lambda name: failed_baseline,
    )
    contract = SimpleNamespace(
        baselines=["fresh-host"],
        plan_execution_id="failed-restore",
        lease_id=7,
        contract_digest="digest",
    )
    result = prepare_mission(
        contract,
        execution_factory=lambda *a, **k: execution,
        scratch_factory=lambda *a, **k: pytest.fail("scratch after failed restore"),
    )
    failure = result["preparation"]["evidence"]["preparation_failure"]
    assert failure["exit_code"] == 1
    assert failure["stdout"] == "bad receipt [REDACTED]"
    assert failure["stderr"] == "TimeoutExpired [REDACTED]"
    assert result["preparation"]["evidence"]["scratch_created"] is False
    assert "private-token" not in json.dumps(result)
