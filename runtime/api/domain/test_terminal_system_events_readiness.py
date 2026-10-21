"""Live Terminal Automation grants gate verification and golden capture."""

import pytest

from yoke_harness import ssh_mac_transport, ssh_mac_golden_capture
from yoke_harness.ssh_mac_terminal_automation_probe import TerminalAutomationProbe
from yoke_harness.test_machine_operations import run_verification_sequence
from yoke_harness.test_machine_types import HostActionResult


@pytest.fixture
def control(monkeypatch):
    control = object.__new__(ssh_mac_transport.SshMacTransport)
    control._user = "tester"
    control.secret_values = ("host-credential",)
    control._run = lambda *a, **kw: pytest.fail("Unexpected remote command")
    monkeypatch.setattr(ssh_mac_transport, "read_console_user", lambda run: "tester")
    monkeypatch.setattr(
        ssh_mac_transport, "read_screen_saver_idle_seconds", lambda *a: 0
    )
    monkeypatch.setattr(
        ssh_mac_transport,
        "verify_terminal_app_control",
        lambda *a, **kw: (True, {"terminal_app_screenshot": True}, None),
    )
    return control


@pytest.mark.parametrize("outcome", ["missing", "timeout"])
@pytest.mark.parametrize("operation", ["verify", "capture"])
def test_missing_live_grant_refuses_by_name_before_capture(
    monkeypatch, control, outcome, operation
):
    code = f"terminal_system_events_automation_{outcome}"
    calls = []

    def probe(run, *, secret_values):
        assert secret_values == control.secret_values
        assert run is control._run
        calls.append("automation")
        return TerminalAutomationProbe(
            code,
            "Terminal->System Events",
            1,
            {"tcc_log": {"output": "pending consent"}},
        )

    monkeypatch.setattr(ssh_mac_transport, "terminal_system_events_automation", probe)
    if operation == "verify":
        rows, error = run_verification_sequence(
            checks=[
                ("connection", lambda: HostActionResult(True, {})),
                ("terminal_bridge", control.check_terminal_bridge),
            ],
            baselines=[],
        )
        assert error == code
        assert not rows[-1]["ok"]
        evidence = rows[-1]
    else:
        # Refuse before any probe, quit, upload, copy or seal can run.
        monkeypatch.setattr(
            ssh_mac_golden_capture,
            "prove_probes_document",
            lambda *a: pytest.fail("Baseline probes ran after failed bridge"),
        )
        result = ssh_mac_golden_capture.capture_golden_baseline(
            control, destination="/Users/Shared/golden"
        )
        assert not result.ok and result.error_code == code
        evidence = result.evidence
    assert calls == ["automation"]
    diagnostic = evidence["capture_diagnostics"]
    assert diagnostic["error_reason"] == code
    assert diagnostic["detail"] == "Terminal->System Events"
    assert diagnostic["tcc_log"]["output"] == "pending consent"
    assert "host" in diagnostic["recovery"]
    if outcome == "missing":
        assert "Privacy & Security > Automation" in diagnostic["recovery"]


@pytest.mark.usefixtures("recorded_harness_clis")
def test_capture_proves_bridge_before_probes_and_copy(monkeypatch, control):
    calls = []
    monkeypatch.setattr(
        ssh_mac_transport,
        "terminal_system_events_automation",
        lambda run, **kw: (
            calls.append("automation") or TerminalAutomationProbe(None, "")
        ),
    )
    monkeypatch.setattr(
        ssh_mac_golden_capture,
        "prove_probes_document",
        lambda *a: calls.append("probes") or HostActionResult(True, {}),
    )
    monkeypatch.setattr(
        ssh_mac_golden_capture,
        "quit_sign_in_apps",
        lambda *a: calls.append("quit") or HostActionResult(True, {}),
    )
    monkeypatch.setattr(
        ssh_mac_golden_capture,
        "execute_golden_capture",
        lambda **kw: calls.append("copy") or HostActionResult(True, {}),
    )
    control.home = "/Users/tester"
    control.path_state = None
    result = ssh_mac_golden_capture.capture_golden_baseline(
        control, destination="/Users/Shared/golden"
    )
    assert result.ok
    assert calls == ["automation", "probes", "quit", "copy"]
