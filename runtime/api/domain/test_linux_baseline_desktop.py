"""Golden capture requires a restored non-blank desktop and proved logout."""

import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import ssh_linux_baseline as baseline
from yoke_harness import ssh_linux_baseline_desktop as desktop
from yoke_harness.test_machine_types import HostActionResult


@pytest.mark.parametrize(
    "failure",
    [None, "reset_roundtrip", "restored_probes", "desktop_frame", "desktop_end"],
)
def test_roundtrip_refuses_each_failed_step_and_always_ends_capture_session(
    monkeypatch, failure
):
    calls = []

    def result(name):
        calls.append(name)
        return HostActionResult(
            name != failure,
            {"recovery": "repair " + name},
            name + "_error" if name == failure else None,
        )

    monkeypatch.setattr(
        baseline, "archive_operation", lambda *a: result("reset_roundtrip")
    )
    monkeypatch.setattr(
        baseline, "prove_linux_probes", lambda *a: result("restored_probes")
    )
    monkeypatch.setattr(desktop, "end_desktop", lambda *a: result("desktop_end"))
    control = SimpleNamespace(capture_screenshot=lambda: result("desktop_frame"))
    captured = HostActionResult(True, {"golden_baseline_path": "/golden"})
    outcome = desktop.prove_capture_roundtrip(control, "/golden", "probes", captured)
    assert outcome.ok is (failure is None)
    assert [row["name"] for row in outcome.evidence["roundtrip_checks"]] == calls
    if failure:
        assert outcome.evidence["failing_step"] == failure
        assert outcome.error_code == "linux_golden_" + failure + "_failed"
    if failure not in {"reset_roundtrip", "restored_probes"}:
        assert calls[-2:] == ["desktop_frame", "desktop_end"]


def test_end_desktop_executes_shared_stop_and_requires_a_valid_receipt():
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        program = shlex.split(command)[2]
        compile(program, "desktop-end", "exec")
        assert "stop_desktop()" in program
        return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True}), "")

    assert desktop.end_desktop(SimpleNamespace(_run=run)).ok
    control = SimpleNamespace(
        _run=lambda *a, **kw: subprocess.CompletedProcess([], 0, "[]", "")
    )
    assert desktop.end_desktop(control).error_code == "linux_desktop_stop_not_proved"


def test_linux_capture_roundtrip_runs_after_probe_seal_and_before_success(monkeypatch):
    calls = []
    monkeypatch.setattr(
        baseline, "prove_linux_probes", lambda *a: HostActionResult(True, {})
    )
    monkeypatch.setattr(
        baseline,
        "archive_operation",
        lambda *a: calls.append("archive") or HostActionResult(True, {}),
    )
    monkeypatch.setattr(
        desktop,
        "prove_capture_roundtrip",
        lambda *a: (
            calls.append("roundtrip")
            or HostActionResult(False, {}, "linux_golden_desktop_frame_failed")
        ),
    )
    control = SimpleNamespace(
        os="linux", upload_remote_text=lambda *a: calls.append("seal")
    )
    outcome = baseline.capture_linux_golden(control, "/golden", None)
    assert calls == ["archive", "seal", "roundtrip"]
    assert not outcome.ok
    assert outcome.error_code == "linux_golden_desktop_frame_failed"


def test_frame_exception_refuses_capture_and_still_ends_session(monkeypatch):
    monkeypatch.setattr(
        baseline, "archive_operation", lambda *a: HostActionResult(True, {})
    )
    monkeypatch.setattr(
        baseline, "prove_linux_probes", lambda *a: HostActionResult(True, {})
    )
    stopped = []
    monkeypatch.setattr(
        desktop,
        "end_desktop",
        lambda *a: stopped.append(True) or HostActionResult(True, {}),
    )

    def capture():
        raise OSError("secret-bearing transport output")

    outcome = desktop.prove_capture_roundtrip(
        SimpleNamespace(capture_screenshot=capture),
        "/golden",
        "probes",
        HostActionResult(True, {}),
    )
    assert outcome.error_code == "linux_golden_desktop_frame_failed"
    assert "OSError" in outcome.evidence["recovery"]
    assert "secret-bearing" not in str(outcome)
    assert stopped == [True]


def test_golden_receipt_keeps_frame_proof_without_screenshot_artifact(monkeypatch):
    monkeypatch.setattr(
        baseline, "archive_operation", lambda *a: HostActionResult(True, {})
    )
    monkeypatch.setattr(
        baseline, "prove_linux_probes", lambda *a: HostActionResult(True, {})
    )
    monkeypatch.setattr(desktop, "end_desktop", lambda *a: HostActionResult(True, {}))
    frame = HostActionResult(
        True,
        {
            "width": 1280,
            "height": 1024,
            "sha256": "a" * 64,
            "capture_artifact": {"content_base64": "private-frame"},
            "artifact_token": "desktop",
        },
    )
    outcome = desktop.prove_capture_roundtrip(
        SimpleNamespace(capture_screenshot=lambda: frame),
        "/golden",
        "probes",
        HostActionResult(True, {}),
    )
    assert outcome.ok and outcome.evidence["width"] == 1280
    assert "capture_artifact" not in outcome.evidence
    assert "private-frame" not in str(outcome.evidence)
