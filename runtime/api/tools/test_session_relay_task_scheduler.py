"""Windows relay supervision contract; no scheduler or administrator needed."""

import subprocess
from dataclasses import replace
import xml.etree.ElementTree as ET

import pytest

from runtime.api.tools.session_relay_release_test_support import relay_instance
from yoke_core.tools import session_relay_task_scheduler as tasks
from yoke_core.tools import session_relay_service as service
pytestmark = pytest.mark.windows
SID = "S-1-5-21-123-456-789-1001"
NS = {"t": tasks.TASK_NS}


class Scheduler:
    def __init__(self, instance):
        self.instance = instance
        self.xml = ""
        self.state = "3"
        self.commands = []
        self.restricted = False
        self.startup_states = []

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
        elif argv == ["schtasks", "/Query", "/FO", "CSV", "/NH"]:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        elif argv[0] == "powershell.exe":
            assert f".GetTask('{self.instance.label}')" in argv[-1]
            out = "missing"
            if self.xml:
                out = self.startup_states.pop(0) if self.startup_states else self.state
                if "$task.Xml" in argv[-1]:
                    out = f"{out}\r\n{self.xml}"
        else:
            pytest.fail(f"Unexpected scheduler command: {argv}")
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


def test_task_runs_the_windowless_interpreter_beside_the_runtime_python(tmp_path):
    instance = relay_instance(tmp_path)
    document = ET.fromstring(tasks.relay_task_document(instance, user_sid=SID))
    command = document.findtext("t:Actions/t:Exec/t:Command", namespaces=NS)
    assert command == str(tasks.relay_runtime_python(instance.state_dir).with_name("pythonw.exe"))
    assert document.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS) == subprocess.list2cmdline(
        ["-I", str(instance.state_dir / "task-runner.py")]
    )


def test_a_task_still_running_the_console_interpreter_is_outdated(tmp_path):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    windowless = str(tasks.relay_task_command(instance.state_dir))
    console = str(tasks.relay_runtime_python(instance.state_dir))
    runner.xml = tasks.relay_task_document(instance, user_sid=SID).replace(windowless, console)
    status = tasks.relay_task_status(instance=instance, runner=runner)
    assert not status.task_current and not service.relay_service_current(status)
    assert "Task/Actions/Exec/Command" in status.reason and "pythonw.exe" in status.reason


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
    body = (instance.state_dir / "task-runner.py").read_text(encoding="utf-8")
    assert repr(str(instance.config_path)) in body
    assert "subprocess.call" in body and "-I" in body
    runner.commands.clear()
    tasks.install_relay_task(instance=instance, runner=runner)
    lifecycle = [argv[1] for argv in runner.commands if argv[0] == "schtasks" and argv[1] in {"/Create", "/End", "/Run"}]
    assert lifecycle == ["/Create", "/End", "/Run"]
    status = tasks.uninstall_relay_task(instance=instance, runner=runner)
    assert not status.task_present and not status.loaded
    assert any("/End" in argv for argv in runner.commands)
    assert any("/Delete" in argv for argv in runner.commands)
    assert not (instance.state_dir / "task-runner.py").exists()


def test_install_polls_only_the_named_task_when_the_full_listing_would_time_out(
    tmp_path, monkeypatch
):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    runner.startup_states = ["3", "2", "4"]
    monkeypatch.setattr(tasks.relay_install, "converge_relay_launcher", lambda *a, **k: None)
    sleeps = []
    monkeypatch.setattr(tasks.time, "sleep", sleeps.append)

    status = tasks.install_relay_task(instance=instance, runner=runner)

    assert status.task_present and status.task_current and status.loaded
    assert sleeps == [0.1, 0.1]
    assert [argv[0] for argv in runner.commands].count("whoami") == 1
    assert [argv[0] for argv in runner.commands].count("powershell.exe") == 4
    assert not any(argv[:2] == ["schtasks", "/Query"] for argv in runner.commands)


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
    reason = tasks.relay_task_status(instance=instance, runner=runner).reason
    assert reason.startswith(
        "relay_task_outdated: Task/Principals/Principal/LogonType is 'Password', "
        "expected 'InteractiveToken'; retry `yoke relay install`"
    )


def test_windows_dispatch_and_unknown_os_refusal(monkeypatch):
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(tasks, "uninstall_relay_task", lambda **kw: "removed")
    assert service.relay_service_operation("uninstall") == "removed"
    monkeypatch.setattr(service.sys, "platform", "unknown-os")
    with pytest.raises(tasks.RelayInstallError, match="relay_os_unsupported.*Recovery"):
        service.relay_service_operation("install")


def test_named_task_status_decodes_utf8_xml(tmp_path):
    fixture_root = tmp_path / "réseau"
    fixture_root.mkdir()
    instance = relay_instance(fixture_root)
    xml = tasks.relay_task_document(instance, user_sid=SID)

    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, f"4\r\n{xml}".encode(), b"")

    status = tasks.relay_task_status(instance=instance, runner=run, account=(SID, "user"))
    assert status.task_current and status.loaded


def test_release_refusal_remains_a_named_installer_error(tmp_path, monkeypatch):
    instance = relay_instance(tmp_path)
    runner = Scheduler(instance)
    def fail(*args, **kwargs):
        raise tasks.RelayReleaseError("release_unavailable", "release unavailable; retry the install")
    monkeypatch.setattr(tasks.relay_install, "converge_relay_launcher", fail)
    with pytest.raises(tasks.RelayInstallError) as raised:
        tasks.install_relay_task(instance=instance, runner=runner)
    assert raised.value.code == "release_unavailable"


def test_supervisor_filesystem_failure_has_reason_and_recovery(monkeypatch):
    monkeypatch.setattr(service.sys, "platform", "win32")
    def fail(**kwargs):
        raise OSError("state path is locked")
    monkeypatch.setattr(tasks, "install_relay_task", fail)
    with pytest.raises(tasks.RelayInstallError, match="state path is locked.*Recovery") as raised:
        service.relay_service_operation("install")
    assert raised.value.code == "relay_service_filesystem_failed"


def test_local_task_keeps_a_stable_interpreter_across_operator_cli_updates(tmp_path, monkeypatch):
    instance = replace(relay_instance(tmp_path), follows_served_release=False)
    runner = Scheduler(instance)
    launcher = tmp_path / "installed" / "yoke.cmd"
    monkeypatch.setattr(tasks.relay_install, "converge_relay_launcher", lambda *a, **k: launcher)
    runtimes = []
    monkeypatch.setattr(tasks, "ensure_relay_runtime", lambda state: runtimes.append(state))
    tasks.install_relay_task(instance=instance, runner=runner)
    assert runtimes == [instance.state_dir]
    root = ET.fromstring(runner.xml)
    assert root.findtext("t:Actions/t:Exec/t:Command", namespaces=NS) == str(tasks.relay_task_command(instance.state_dir))
    body = (instance.state_dir / "task-runner.py").read_text(encoding="utf-8")
    assert repr(str(launcher)) in body


def test_scheduler_export_omitting_defaults_is_current_and_every_change_is_named(tmp_path):
    expected = tasks.relay_task_document(relay_instance(tmp_path), user_sid=SID)
    exported = ET.fromstring(expected)
    trigger = exported.find("t:Triggers/t:LogonTrigger", NS)
    trigger.remove(trigger.find("t:Enabled", NS))
    settings = exported.find("t:Settings", NS)
    for name in ("Enabled", "AllowHardTerminate", "MultipleInstancesPolicy"):
        settings.remove(settings.find(f"t:{name}", NS))
    assert tasks._difference(ET.tostring(exported, encoding="unicode"), expected) == ""
    settings.remove(settings.find("t:ExecutionTimeLimit", NS))
    settings.find("t:StartWhenAvailable", NS).text = "false"
    assert tasks._difference(ET.tostring(exported, encoding="unicode"), expected) == (
        "Task/Settings/StartWhenAvailable is 'false', expected 'true'; "
        "Task/Settings/ExecutionTimeLimit is missing"
    )


def test_scheduler_export_naming_the_account_instead_of_its_sid_is_current(tmp_path):
    expected = tasks.relay_task_document(relay_instance(tmp_path), user_sid=SID)
    exported = expected.replace(SID, r"HOST\user", 1)  # the LogonTrigger's UserId
    assert tasks._difference(exported, expected, account_name=r"host\USER") == ""
    assert tasks._difference(exported, expected, account_name=r"HOST\other") == (
        rf"Task/Triggers/LogonTrigger/UserId is 'HOST\\user', expected '{SID}'"
    )
