"""WSL warnings describe the selected checkout and the caller's Linux host."""

from pathlib import Path

import pytest

from yoke_core.engines import doctor_hc_wsl as checks
from yoke_core.engines.doctor_applicability_declarations import applicability_for
from yoke_core.engines.doctor_registry import HEALTH_CHECKS
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_source_root import bound_source_root
from yoke_harness import wsl


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_non_linux_checks_are_not_applicable(monkeypatch, platform):
    monkeypatch.setattr(checks.sys, "platform", platform)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    rec = RecordCollector()
    checks.hc_windows_mount_checkout(None, DoctorArgs(), rec)
    checks.hc_wsl_systemd(None, DoctorArgs(), rec)
    assert [r.result for r in rec.results] == ["N/A", "N/A"]


@pytest.mark.parametrize(
    "root,verdict",
    [
        ("/mnt/c/projects/app", "WARN"),
        ("/mnt/D/app", "WARN"),
        ("/home/me/app", "PASS"),
        ("/mnt/cache/app", "PASS"),
    ],
)
def test_mount_warning_uses_bound_project_checkout(monkeypatch, root, verdict):
    monkeypatch.setattr(checks.sys, "platform", "linux")
    rec = RecordCollector()
    with bound_source_root(root):
        checks.hc_windows_mount_checkout(None, DoctorArgs(project="customer"), rec)
    assert rec.results[0].result == verdict
    assert root in rec.results[0].detail


def test_mount_check_follows_symlinks(monkeypatch, tmp_path):
    monkeypatch.setattr(checks.sys, "platform", "linux")
    checkout = tmp_path / "checkout"
    checkout.symlink_to("/mnt/c/project")
    rec = RecordCollector()
    with bound_source_root(checkout):
        checks.hc_windows_mount_checkout(None, DoctorArgs(), rec)
    assert rec.results[0].result == "WARN"


@pytest.mark.parametrize("running,verdict", [(True, "PASS"), (False, "WARN")])
def test_wsl_systemd_warning(monkeypatch, running, verdict):
    monkeypatch.setattr(checks, "is_wsl", lambda: True)
    monkeypatch.setattr(checks, "systemd_running", lambda: running)
    rec = RecordCollector()
    checks.hc_wsl_systemd(None, DoctorArgs(), rec)
    assert rec.results[0].result == verdict
    if not running:
        assert "wsl --shutdown" in rec.results[0].detail
        assert "yoke wsl setup" in rec.results[0].detail


def test_linux_outside_wsl_is_not_applicable(monkeypatch):
    monkeypatch.setattr(checks, "is_wsl", lambda: False)
    rec = RecordCollector()
    checks.hc_wsl_systemd(None, DoctorArgs(), rec)
    assert rec.results[0].result == "N/A"


def test_unreadable_pid_one_warns(monkeypatch):
    monkeypatch.setattr(checks, "is_wsl", lambda: True)

    def unreadable():
        raise PermissionError("proc unavailable")

    monkeypatch.setattr(checks, "systemd_running", unreadable)
    rec = RecordCollector()
    checks.hc_wsl_systemd(None, DoctorArgs(), rec)
    assert rec.results[0].result == "WARN"
    assert "wsl_pid1_unreadable" in rec.results[0].detail


@pytest.mark.parametrize(
    "platform,distro,kernel,expected",
    [
        ("linux", "Ubuntu", "generic", True),
        ("linux", "", "Microsoft-standard", True),
        ("linux", "", "microsoft-standard-WSL2", True),
        ("linux", "", "generic", False),
        ("darwin", "Ubuntu", "Microsoft", False),
    ],
)
def test_wsl_detection(monkeypatch, platform, distro, kernel, expected):
    monkeypatch.setattr(wsl.sys, "platform", platform)
    monkeypatch.setenv("WSL_DISTRO_NAME", distro)
    monkeypatch.setattr(Path, "read_text", lambda self: kernel)
    assert wsl.is_wsl() is expected


def test_wsl_detection_without_proc(monkeypatch):
    monkeypatch.setattr(wsl.sys, "platform", "linux")
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)

    def unreadable(self):
        raise FileNotFoundError()

    monkeypatch.setattr(Path, "read_text", unreadable)
    assert not wsl.is_wsl()


@pytest.mark.parametrize("comm,expected", [("systemd\n", True), ("init\n", False)])
def test_pid_one_is_the_systemd_authority(monkeypatch, comm, expected):
    monkeypatch.setattr(Path, "read_text", lambda self: comm)
    assert wsl.systemd_running() is expected


def test_checks_are_registered_and_declared_for_local_machine():
    for slug in ("windows-mount-checkout", "wsl-systemd"):
        assert slug in {hc.slug for hc in HEALTH_CHECKS}
        assert applicability_for(slug).runtimes == frozenset({"local"})
    assert applicability_for("windows-mount-checkout").requires_source_checkout
