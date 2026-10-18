"""Projectless commands preserve scope and machine-owned output."""

import pytest

from yoke_cli.commands.adapters import doctor
from yoke_cli.config import status_doctor, universe_export_download
from yoke_cli.project_install import runner
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.project_defaults import MissingProjectError
from yoke_core.domain import machine_config_status
from yoke_core.domain.universe_export_destination import resolve_export_destination


def test_install_refuses_non_git_before_bundle_or_config(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner, "_resolve_bundle", lambda *_a, **_k: pytest.fail("bundle read")
    )
    with pytest.raises(ProjectInstallError, match="project_git_required.*git init"):
        runner.install(tmp_path, project_id=7, force=True, commit=False)
    assert list(tmp_path.iterdir()) == []


def test_doctor_last_run_refuses_before_dispatch(monkeypatch, capsys):
    def refuse(_project):
        raise MissingProjectError(
            "project_required: pass --project P. Accessible projects: mine."
        )

    monkeypatch.setattr(doctor, "required_project_context", refuse)
    monkeypatch.setattr(
        doctor, "dispatch_and_emit", lambda **_k: pytest.fail("unscoped read")
    )
    assert doctor.doctor_last_run_get([]) == 2
    assert "Accessible projects: mine" in capsys.readouterr().err


def test_status_without_project_never_reads_a_foreign_doctor_receipt(monkeypatch):
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_k: pytest.fail("unscoped doctor receipt"),
    )
    report = status_doctor.attach_doctor({"server": {"reachable": True}})
    assert report["doctor"]["summary"].startswith("health unverified")
    # Doctor refuses without a project, so the hint names a form that works.
    assert "--project P" in report["doctor"]["summary"]
    assert "yoke projects list" in report["doctor"]["summary"]


def test_export_defaults_stay_outside_cwd(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    cwd = tmp_path / "projectless"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    local = resolve_export_destination(None, "demo")
    https = universe_export_download._destination(None, "demo.tar")
    assert local.parent == https.parent == home / "exports"
    assert list(cwd.iterdir()) == []
    assert resolve_export_destination(str(cwd) + "/", "demo").parent == cwd


def test_project_mapping_is_the_same_warning_in_cli_and_core(tmp_path, monkeypatch):
    from yoke_cli.config import status

    config = tmp_path / "config.json"
    config.write_text("{}")
    for module in (status, machine_config_status):
        report = module._project_status(tmp_path, config)
        (issue,) = report["issues"]
        assert issue["code"] == "project_mapping_missing"
        assert issue["severity"] == "warning"
        assert "yoke project register" in issue["hint"]


def test_default_export_folder_obstruction_teaches_recovery(tmp_path, monkeypatch):
    from yoke_core.domain.universe_export_destination import UniverseExportError

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    (tmp_path / "exports").write_text("preserve this file")
    with pytest.raises(
        UniverseExportError, match="universe_export_destination_unavailable.*--out"
    ):
        resolve_export_destination(None, "demo")
    with pytest.raises(
        universe_export_download.UniverseExportDownloadError,
        match="universe_export_destination_unavailable.*--out",
    ):
        universe_export_download._destination(None, "demo.tar")
    assert (tmp_path / "exports").read_text() == "preserve this file"


def test_install_refuses_a_plain_folder_inside_another_repository(
    tmp_path, monkeypatch
):
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    child = tmp_path / "plain-folder"
    child.mkdir()
    monkeypatch.setattr(
        runner, "_resolve_bundle", lambda *_a, **_k: pytest.fail("bundle read")
    )
    with pytest.raises(ProjectInstallError, match="project_git_required"):
        runner.install(child, project_id=7)
    assert list(child.iterdir()) == []
