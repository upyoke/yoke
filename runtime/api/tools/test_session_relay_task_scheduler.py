"""Windows relay supervision contract; no scheduler or administrator needed."""

import subprocess
import xml.etree.ElementTree as ET

import pytest

from runtime.api.tools.session_relay_release_test_support import relay_instance
from yoke_core.tools import session_relay_task_scheduler as tasks
from yoke_core.tools import session_relay_service as service

SID = "S-1-5-21-123-456-789-1001"
NS = {"t": tasks.TASK_NS}


class Scheduler:
    def __init__(self, instance):
        self.instance = instance
        self.xml = ""
        self.state = "3"
        self.commands = []
        self.restricted = False

    def __call__(self, argv, **kwargs):
        self.commands.append(argv)
        assert kwargs["timeout"] == 15
        code, out, err = 0, "", ""
        if argv[0] == "whoami":
            out = f'"user","{SID}"\n'
        elif self.restricted:
            code, err = 1, "Access is denied by policy"
        elif "/Create" in argv:
            from pathlib import Path
            self.xml = Path(argv[argv.index("/XML") + 1]).read_text(encoding="utf-16")
        elif "/Run" in argv:
            self.state = "4"
        elif "/End" in argv:
            self.state = "3"
        elif "/Delete" in argv:
            self.xml = ""
        elif "/XML" in argv:
            code, out = (0, self.xml) if self.xml else (1, "not found")
        elif argv[0] == "powershell.exe":
            out = self.state
        return subprocess.CompletedProcess(argv, code, out, err)


def test_task_has_per_user_login_trigger_no_boot_trigger_and_runs_on_battery(tmp_path):
    document = ET.fromstring(tasks.relay_task_document(relay_instance(tmp_path), user_sid=SID))
    assert document.findtext("t:Principals/t:Principal/t:UserId", namespaces=NS) == SID
    assert document.findtext("t:Principals/t:Principal/t:LogonType", namespaces=NS) == "InteractiveToken"
    assert document.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=NS) == "LeastPrivilege"
    assert document.findtext("t:Triggers/t:LogonTrigger/t:UserId", namespaces=NS) == SID
    assert document.find("t:Triggers/t:BootTrigger", NS) is None
    for name in ("DisallowStartIfOnBatteries", "StopIfGoingOnBatteries"):
        assert document.findtext(f"t:Settings/t:{name}", namespaces=NS) == "false"
    assert document.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=NS) == "PT0S"
    assert document.findtext("t:Settings/t:MultipleInstancesPolicy", namespaces=NS) == "IgnoreNew"


def test_install_status_and_uninstall_roundtrip(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    launcher = tmp_path / "runtime" / "Scripts" / "yoke.cmd"
    monkeypatch.setattr(tasks.relay_install, "converge_relay_launcher", lambda *a, **k: launcher)
    status = tasks.install_relay_task(instance=instance, runner=runner)
    assert status.loaded and service.relay_service_current(status)
    assert service.relay_service_present(status)
    payload = service.relay_service_payload(status)
    assert payload["supervisor"] == "Task Scheduler"
    assert "sign-out" in payload["logout_behavior"]
    body = (instance.state_dir / "task-runner.py").read_text()
    assert str(instance.config_path) in body
    assert "subprocess.call" in body and "-I" in body
    status = tasks.uninstall_relay_task(instance=instance, runner=runner)
    assert not status.task_present and not status.loaded
    assert any("/End" in argv for argv in runner.commands)
    assert any("/Delete" in argv for argv in runner.commands)
    assert not (instance.state_dir / "task-runner.py").exists()


def test_signout_and_reboot_before_login_are_unavailable_next_login_runs(tmp_path):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    runner.xml = tasks.relay_task_document(instance, user_sid=SID)
    for state in ("3", "3", "4"):
        runner.state = state
        status = tasks.relay_task_status(instance=instance, runner=runner)
        assert status.task_current and status.task_present
        assert status.loaded is (state == "4")


def test_scheduler_restriction_is_not_reported_as_missing_or_healthy(tmp_path):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    runner.restricted = True
    status = tasks.relay_task_status(instance=instance, runner=runner)
    assert not status.supported and not status.loaded
    assert "Access is denied by policy" in status.reason
    assert "Recovery:" in status.reason
    assert not service.relay_service_current(status)
    with pytest.raises(tasks.RelayInstallError, match="permit this user's"):
        tasks.install_relay_task(instance=instance, runner=runner)
    with pytest.raises(tasks.RelayInstallError):
        tasks.uninstall_relay_task(instance=instance, runner=runner)


def test_disabled_and_changed_tasks_need_repair(tmp_path):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    runner.xml = tasks.relay_task_document(instance, user_sid=SID)
    runner.state = "1"
    status = tasks.relay_task_status(instance=instance, runner=runner)
    assert "disabled" in status.reason
    runner.state = "3"
    runner.xml = runner.xml.replace("InteractiveToken", "Password")
    assert "outdated" in tasks.relay_task_status(instance=instance, runner=runner).reason


def test_windows_dispatch_and_unknown_os_refusal(monkeypatch):
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(tasks, "uninstall_relay_task", lambda **kw: "removed")
    assert service.relay_service_operation("uninstall") == "removed"
    monkeypatch.setattr(service.sys, "platform", "unknown-os")
    with pytest.raises(tasks.RelayInstallError, match="relay_os_unsupported.*Recovery"):
        service.relay_service_operation("install")


def test_scheduler_xml_decodes_utf16_export(tmp_path):
    instance = relay_instance(tmp_path)
    xml = tasks.relay_task_document(instance, user_sid=SID)
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, xml.encode("utf-16"), b"")
    result = tasks._run(["schtasks", "/Query", "/XML"], run)
    assert result.stdout == xml


def test_release_refusal_remains_a_named_installer_error(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    def fail(*args, **kwargs):
        raise tasks.RelayReleaseError("release_unavailable", "release unavailable; retry the install")
    monkeypatch.setattr(tasks.relay_install, "converge_relay_launcher", fail)
    with pytest.raises(tasks.RelayInstallError) as raised:
        tasks.install_relay_task(instance=instance, runner=runner)
    assert raised.value.code == "release_unavailable"


def test_task_owner_recycles_relay_without_finishing_scheduled_action(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    monkeypatch.setattr(tasks.relay_install, "converge_relay_launcher", lambda *a, **k: tmp_path / "yoke.cmd")
    tasks.install_relay_task(instance=instance, runner=runner)
    source = (instance.state_dir / "task-runner.py").read_text()
    results = iter([tasks.WINDOWS_RELAY_RESTART_CODE, 0])
    calls = []
    monkeypatch.setattr(tasks.os, "environ", {})
    monkeypatch.setattr(tasks.subprocess, "call", lambda argv, **kw: calls.append(argv) or next(results))
    with pytest.raises(SystemExit) as exited:
        exec(compile(source, "task-runner.py", "exec"), {})
    assert exited.value.code == 0
    assert len(calls) == 2 and calls[0] == calls[1]
    assert tasks.os.environ[tasks.WINDOWS_RELAY_RUNNER_ENV] == "1"
