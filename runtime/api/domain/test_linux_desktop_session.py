"""Unattended XFCE startup, password transport, and shared reset admission."""

import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import linux_desktop_state as state
from yoke_harness.linux_desktop_session import desktop_command
from yoke_harness.ssh_linux_reset_preconditions import DESKTOP_PROGRAM

PASSWORD = "desktop-secret-with-$()-and-quotes"
SESSION = {
    "pid": 42,
    "start": "123456",
    "session_id": "c2",
    "environment": {
        "DISPLAY": ":10",
        "XAUTHORITY": "/home/test/.Xauthority",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    },
}


@pytest.fixture
def host(tmp_path, monkeypatch):
    marker = tmp_path / "ownership.json"
    marker.touch(mode=0o600)

    def ownership():
        return marker.open("r+")

    monkeypatch.setattr(state, "ownership_file", ownership)
    monkeypatch.setattr(state, "graphical_sessions", lambda: [])
    monkeypatch.setattr(state, "human_desktop_exists", lambda *a: False)
    monkeypatch.setattr(state, "rdp_connected", lambda *a: False)
    monkeypatch.setattr(state, "desktop_sessions", lambda: [])
    return marker


@pytest.mark.parametrize("display", [":10", ":10.0"])
def test_start_and_reuse_keep_password_only_on_stdin(host, monkeypatch, display):
    calls = []
    session = {**SESSION, "environment": {**SESSION["environment"], "DISPLAY": display}}

    def run(argv, **kw):
        calls.append((argv, kw))
        monkeypatch.setattr(state, "desktop_sessions", lambda: [session])
        return subprocess.CompletedProcess(argv, 0, "ok data=1 display=:10\n", "")

    monkeypatch.setattr(state.subprocess, "run", run)
    started = state.ensure_desktop(PASSWORD)
    assert started == {
        "environment": session["environment"],
        "desktop_session": "started",
    }
    assert state.ensure_desktop(None)["desktop_session"] == "reused"
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:7] == ["xrdp-sesrun", "-s", "::1", "-t", "Xorg", "-F", "0"]
    assert kwargs["input"] == PASSWORD + "\n"
    assert PASSWORD not in str(argv) + str(started) + host.read_text()
    assert json.loads(host.read_text())["session"] == session
    assert host.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("blocked", ["human", "rdp", "ambiguous"])
def test_no_start_with_existing_human_or_ambiguous_desktop(host, monkeypatch, blocked):
    if blocked == "human":
        monkeypatch.setattr(state, "human_desktop_exists", lambda *a: True)
    elif blocked == "rdp":
        monkeypatch.setattr(state, "rdp_connected", lambda *a: True)
    else:
        monkeypatch.setattr(state, "desktop_sessions", lambda: [SESSION, SESSION])
    monkeypatch.setattr(
        state.subprocess, "run", lambda *a, **kw: pytest.fail("must not start")
    )
    with pytest.raises(RuntimeError, match="session_ambiguous.*RDP"):
        state.ensure_desktop(PASSWORD)


def test_existing_human_xfce_is_reused_without_password(host, monkeypatch):
    monkeypatch.setattr(state, "desktop_sessions", lambda: [SESSION])
    monkeypatch.setattr(
        state.subprocess, "run", lambda *a, **kw: pytest.fail("must not start")
    )
    assert state.ensure_desktop(None)["desktop_session"] == "reused"
    assert host.read_text() == ""


@pytest.mark.parametrize("failure", ["missing", "refused", "unavailable", "timeout"])
def test_start_refusals_preserve_output_redact_password_and_teach_product_recovery(
    host, monkeypatch, failure
):
    def run(argv, **kwargs):
        if failure == "unavailable":
            raise FileNotFoundError("xrdp-sesrun missing")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 30, output=PASSWORD)
        return subprocess.CompletedProcess(
            argv, 1, "connect error - Operation now in progress\n", PASSWORD
        )

    monkeypatch.setattr(state.subprocess, "run", run)
    with pytest.raises(RuntimeError) as refused:
        state.ensure_desktop(None if failure == "missing" else PASSWORD)
    message = str(refused.value)
    assert "Repair the registered fixture secret" in message
    assert "rerun the product GUI operation" in message
    assert PASSWORD not in message
    assert host.read_text() == ""
    if failure == "refused":
        assert "connect error - Operation now in progress\n" in str(refused.value)


def test_gui_command_reports_startup_and_transmits_secret_only_as_input():
    calls = []

    def run(command, **kw):
        calls.append((command, kw))
        receipt = {"environment": SESSION["environment"], "desktop_session": "started"}
        tokens = shlex.split(command)
        if len(tokens) == 7:
            directory = json.loads(tokens[-4])
            settled = {
                "command_id": directory.rsplit("/", 1)[-1],
                "termination_verified": True,
                "returncode": 0,
            }
            return subprocess.CompletedProcess(
                command,
                0,
                "GUI output",
                "YOKE_COMMAND_RECEIPT:" + json.dumps(settled) + "\n",
            )
        return subprocess.CompletedProcess(command, 0, json.dumps(receipt), "")

    control = SimpleNamespace(
        _run=run, desktop_password=PASSWORD, secret_values=(PASSWORD,)
    )
    result = desktop_command(control, ["xdotool", "key", "Return"])
    assert result.desktop_session == "started" and result.stdout == "GUI output"
    assert calls[0][1]["input_text"] == PASSWORD + "\n"
    assert all(PASSWORD not in command for command, _ in calls)
    assert json.loads(shlex.split(calls[1][0])[-3]) == ["xdotool", "key", "Return"]
    assert PASSWORD not in str(result)


def test_transport_diagnostic_is_redacted():
    control = SimpleNamespace(
        _run=lambda *a, **kw: subprocess.CompletedProcess(
            [], 69, "", PASSWORD + " refusal"
        ),
        desktop_password=PASSWORD,
        secret_values=(PASSWORD,),
    )
    with pytest.raises(RuntimeError) as refused:
        desktop_command(control, ["true"])
    assert PASSWORD not in str(refused.value) and "refusal" in str(refused.value)


@pytest.mark.parametrize("human", [False, True])
def test_reset_stops_owned_desktop_only_when_no_human_has_adopted_it(
    host, monkeypatch, human
):
    monkeypatch.setattr(
        state, "owned_desktop", lambda: {**SESSION, "rdp_port": state.RDP_PORT}
    )
    monkeypatch.setattr(state, "human_desktop_exists", lambda *a: human)
    live = [SESSION]
    monkeypatch.setattr(state, "desktop_sessions", lambda: live)
    signals = []

    def kill(pid, number):
        signals.append((pid, number))
        live.clear()

    monkeypatch.setattr(state.os, "kill", kill)
    if human:
        with pytest.raises(RuntimeError, match="desktop_logged_in"):
            state.stop_owned_desktop()
        assert not signals
    else:
        state.stop_owned_desktop()
        assert signals == [(SESSION["pid"], state.signal.SIGTERM)]
        assert host.read_text() == ""


def test_reset_never_signals_recycled_pid(host, monkeypatch):
    monkeypatch.setattr(
        state, "owned_desktop", lambda: {**SESSION, "rdp_port": state.RDP_PORT}
    )
    monkeypatch.setattr(
        state, "desktop_sessions", lambda: [{**SESSION, "start": "new-process"}]
    )
    monkeypatch.setattr(state.os, "kill", lambda *a: pytest.fail("recycled PID"))
    state.stop_owned_desktop()


@pytest.mark.parametrize(
    "human", ["mounted", "child-mount", "xfce", "graphical", "rdp", "none"]
)
def test_startup_and_reset_use_same_human_probe(tmp_path, monkeypatch, human):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    home = tmp_path / "home"
    target = (
        str(home / "thinclient_drives" / "shared")
        if human == "child-mount"
        else "/other"
    )
    (proc / "self/mountinfo").write_text(f"1 2 0:0 / {target} rw - tmpfs tmpfs rw\n")
    if human == "xfce":
        (proc / "42").mkdir()
        (proc / "42/comm").write_text("xfce4-session\n")
    real_path = type(tmp_path)
    monkeypatch.setattr(
        state, "Path", lambda value: proc if str(value) == "/proc" else real_path(value)
    )
    monkeypatch.setattr(state.os.path, "ismount", lambda _: human == "mounted")
    monkeypatch.setattr(
        state,
        "graphical_sessions",
        lambda: [{"id": "c1"}] if human == "graphical" else [],
    )
    monkeypatch.setattr(state, "rdp_connected", lambda *a: human == "rdp")
    owned = {**SESSION, "rdp_port": state.RDP_PORT} if human == "rdp" else None
    assert state.human_desktop_exists(home, owned) == (human != "none")
    assert "human_desktop_exists(home, owned_desktop())" in DESKTOP_PROGRAM


def test_machine_password_is_read_from_exact_capability_and_added_to_redaction(
    monkeypatch,
):
    from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
    from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport
    from yoke_cli.config import capability_secrets

    calls = []
    control = SimpleNamespace(secret_values=("ssh-key",))
    monkeypatch.setattr(
        SshTestMachineTransport,
        "from_contract",
        classmethod(lambda cls, contract: control),
    )
    monkeypatch.setattr(
        capability_secrets,
        "read_machine_capability_secret",
        lambda *a: calls.append(a) or PASSWORD,
    )
    contract = SimpleNamespace(
        project="project", settings={"resource_name": "lab", "desktop_port": "3390"}
    )
    assert SshLinuxHostOperations.from_contract(contract) is control
    assert calls == [("project", "test-machine:lab", "desktop_password")]
    assert control.desktop_password == PASSWORD
    assert PASSWORD in control.secret_values and control.desktop_port == 3390


def test_linux_desktop_access_runs_shared_startup_before_opening_route(
    tmp_path, monkeypatch
):
    from pathlib import Path
    from yoke_harness import desktop_access as desktop
    import yoke_harness.linux_desktop_session as session

    key = tmp_path / "key"
    key.write_text("key")
    monkeypatch.setattr(desktop, "read_machine_capability_secret", lambda *a: PASSWORD)
    monkeypatch.setattr(desktop, "machine_capability_secret_path", lambda *a: key)
    calls = []

    def ensure(control):
        assert control.desktop_password == PASSWORD
        control._run("remote-probe", input_text=PASSWORD + "\n")
        calls.append("ensure")
        return {"desktop_session": "started"}

    monkeypatch.setattr(session, "ensure_desktop", ensure)

    def run(argv, **kw):
        assert PASSWORD not in str(argv)
        if argv[-1] == "id -un":
            assert kw["input"] is None
            calls.append("identity")
            return subprocess.CompletedProcess(argv, 0, "test\n", "")
        assert kw["input"] == PASSWORD + "\n"
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(desktop.subprocess, "run", run)
    monkeypatch.setattr(desktop, "_check_desktop", lambda *a: calls.append("route"))
    result = desktop.open_desktop_access(
        project="project",
        machine="lab",
        settings={
            "os": "linux",
            "host": "lab.invalid",
            "user": "test",
            "desktop_route": "direct",
            "desktop_protocol": "rdp",
            "desktop_port": "3389",
            "desktop_user": "test",
        },
    )
    try:
        assert calls == ["identity", "ensure", "route"]
        assert result["desktop_session"] == "started"
        assert PASSWORD not in json.dumps(result)
    finally:
        Path(result["password_file"]).unlink()
