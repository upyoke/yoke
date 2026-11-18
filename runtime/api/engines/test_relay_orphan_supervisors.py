"""Doctor only reclaims jobs with a verified Yoke pin to a missing config."""

from pathlib import Path
import subprocess

import pytest

from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV, HOME_ENV
from yoke_contracts.machine_config.relay_instance import (
    RELAY_BASE_LABEL,
    RELAY_STATE_ROOT_NAME,
    RelayInstance,
    relay_instance_label,
)
from yoke_core.domain.relay_systemd_status import relay_unit_document
from yoke_core.engines import doctor_hc_session_relay_orphans as doctor
from yoke_core.engines import relay_orphan_supervisors as supervisors
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.tools.session_relay_task_scheduler import relay_task_document


def _instance(root: Path, name: str, *, live: bool = False) -> RelayInstance:
    config = root / f"{name} % config.json"
    if live:
        config.write_text("{}", encoding="utf-8")
    label = relay_instance_label(config_path=config, environment="test")
    return RelayInstance(
        environment="test", config_path=config, yoke_home=root,
        protected=False, label=label, machine_active=False,
        state_dir=root / RELAY_STATE_ROOT_NAME / label.rsplit(".", 1)[1],
        follows_served_release=True,
    )


def _check(*, fix=False):
    rec = RecordCollector()
    doctor.hc_session_relay_orphans(None, DoctorArgs(fix=fix), rec)
    return rec.results[0]


@pytest.mark.linux_only(reason="systemd relay jobs are Linux user services")
def test_doctor_reports_and_reclaims_only_orphaned_systemd_units(tmp_path, monkeypatch):
    live = _instance(tmp_path, "live", live=True)
    orphan = _instance(tmp_path, "orphan")
    live_unit = tmp_path / f"{live.label}.service"
    orphan_unit = tmp_path / f"{orphan.label}.service"
    live_unit.write_text(relay_unit_document(live), encoding="utf-8")
    orphan_unit.write_text(relay_unit_document(orphan), encoding="utf-8")
    canonical = tmp_path / f"{RELAY_BASE_LABEL}.service"
    canonical.write_text(relay_unit_document(orphan), encoding="utf-8")
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(doctor, "relay_unit_directory", lambda: tmp_path)
    monkeypatch.setattr(supervisors, "reclaim_systemd",
                        lambda unit, reclaim=supervisors.reclaim_systemd: reclaim(unit, runner=run))
    found = _check()
    assert found.result == "FAIL"
    assert orphan.label in found.detail
    assert live.label not in found.detail
    assert orphan_unit.exists()
    assert commands == []

    repaired = _check(fix=True)
    assert repaired.result == "PASS"
    assert orphan.label in repaired.detail
    assert not orphan_unit.exists()
    assert live_unit.exists() and canonical.exists()
    assert commands == [
        ["systemctl", "--user", "disable", "--now", orphan_unit.name],
        ["systemctl", "--user", "daemon-reload"],
    ]


@pytest.mark.windows_only(reason="Task Scheduler exports Windows paths and Windows account principals")
def test_doctor_reports_and_reclaims_only_current_users_orphaned_tasks(tmp_path, monkeypatch):
    sid = "S-1-5-21-123"
    live = _instance(tmp_path, "live", live=True)
    orphan = _instance(tmp_path, "orphan")
    foreign = _instance(tmp_path, "foreign")
    documents = {RELAY_BASE_LABEL: "canonical"}
    for instance, owner in [(live, sid), (orphan, sid), (foreign, "S-1-5-21-456")]:
        instance.state_dir.mkdir(parents=True)
        pins = {CONFIG_FILE_ENV: str(instance.config_path), HOME_ENV: str(instance.yoke_home)}
        (instance.state_dir / "task-runner.py").write_text(
            f"os.environ.update({pins!r})\n"
            "code = subprocess.call(['yoke', '--env', 'test', 'relay', 'serve'])\n",
            encoding="utf-8",
        )
        documents[instance.label] = relay_task_document(instance, user_sid=owner)

    changes = []

    def run(argv, **kwargs):
        if argv[0] == "whoami":
            content = f'"MACHINE\\user","{sid}"\n'
        elif argv[0] == "powershell.exe":
            assert orphan.label in argv[-1]
            content = "4\n"
        elif argv[1:4] == ["/Query", "/FO", "CSV"]:
            content = "".join(f'"\\{label}","N/A","Ready"\n' for label in documents)
        elif argv[1] == "/Query":
            content = documents[argv[3]]
        else:
            changes.append(argv)
            if argv[1] == "/Delete":
                del documents[argv[3]]
            content = ""
        return subprocess.CompletedProcess(argv, 0, content, "")

    monkeypatch.setattr(supervisors, "scan_tasks",
                        lambda scan=supervisors.scan_tasks: scan(runner=run))
    monkeypatch.setattr(supervisors, "reclaim_task",
                        lambda label, reclaim=supervisors.reclaim_task: reclaim(label, runner=run))

    found = _check()
    assert found.result == "FAIL"
    assert orphan.label in found.detail
    assert live.label not in found.detail and foreign.label not in found.detail
    assert changes == []

    repaired = _check(fix=True)
    assert repaired.result == "PASS"
    assert orphan.label in repaired.detail
    assert set(documents) == {live.label, foreign.label, RELAY_BASE_LABEL}
    assert changes == [
        ["schtasks", "/End", "/TN", orphan.label],
        ["schtasks", "/Delete", "/TN", orphan.label, "/F"],
    ]
