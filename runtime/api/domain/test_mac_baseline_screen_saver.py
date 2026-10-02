"""The captured current-host screen saver preference stays disabled after restore."""

import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import ssh_mac_golden_capture
from yoke_harness.ssh_host_baselines import SshHostBaselines
from yoke_harness.ssh_mac_baseline_probes import prove_declared_probes
from yoke_harness.ssh_mac_host_session_state import SCREEN_SAVER_READ_COMMAND
from yoke_harness.standard_baseline_probes import standard_probes
from yoke_harness.test_machine_types import HostActionResult


def _saver_program():
    return next(
        p["argv"][2]
        for p in standard_probes("macos")
        if p["name"] == "macOS screen saver disabled"
    )


@pytest.mark.parametrize(
    "exit_code,value", [(0, "0\n"), (0, "1200"), (1, ""), (0, "invalid")]
)
def test_screen_saver_assertion_reads_current_host_without_writing(
    monkeypatch, capsys, exit_code, value
):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=exit_code, stdout=value, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as result:
        exec(compile(_saver_program(), "screen-saver-probe", "exec"), {})
    assert result.value.code == (0 if exit_code == 0 and value.strip() == "0" else 1)
    assert calls == [shlex.split("/usr/bin/" + SCREEN_SAVER_READ_COMMAND)]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("restored_idle", [0, 1200])
def test_capture_seals_screen_saver_check_and_reset_replays_it(
    monkeypatch, restored_idle
):
    state = {"idle": 0, "document": None, "reset": False}
    contexts = []
    program = _saver_program()

    def archive(**kwargs):
        state["document"] = kwargs["probes_document"]
        return HostActionResult(True, {})

    monkeypatch.setattr(ssh_mac_golden_capture, "execute_golden_capture", archive)

    class Control(SshHostBaselines):
        golden_baseline_path = "/srv/golden"
        home = "/Users/tester"
        path_state = None
        run_remote_command = None
        upload_remote_text = None

        def run_command(self, argv, **kwargs):
            code = 0
            if argv[2] == program:
                contexts.append((state["reset"], kwargs["required_session_context"]))
                code = 0 if state["idle"] == 0 else 1
            return SimpleNamespace(returncode=code, stdout="", stderr="")

        def read_remote_text(self, path):
            assert path == self.golden_baseline_path + ".probes"
            return state["document"]

        def reset_installer_test_host(self):
            state.update(reset=True, idle=restored_idle)
            return HostActionResult(True, {"home_restored": True})

        def prove_user_equivalent(self):
            return prove_declared_probes(self)

    control = Control()
    captured = ssh_mac_golden_capture.capture_golden_baseline(
        control, destination=control.golden_baseline_path
    )
    assert captured.ok
    restored = control.reach_baseline("fresh-host")
    assert restored.ok is (restored_idle == 0)
    assert contexts == [(False, "gui"), (True, "gui")]
    if restored_idle:
        assert restored.error_code == "baseline_probe_failed"
        proof = restored.evidence["user_equivalence"]
        assert proof["probes"][-1]["name"] == "macOS screen saver disabled"
        assert "before capture" in proof["recovery"]
        assert "reset roundtrip" in proof["recovery"]
