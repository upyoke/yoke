"""Direct PATH repair checks every installed supported shell context."""

import errno
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import path_doctor as adapter
from yoke_cli.config import onboard_apply_path
from yoke_cli.config.path_doctor import PathDiagnosis, ToolResolution
from yoke_contracts.testing.real_home_isolation import set_home


def diagnosis(needs_fix=False):
    return PathDiagnosis(
        current_shell="bash", tool_bin_dir="/tmp/bin", current_on_path=True,
        current_resolved=[ToolResolution("yoke", "/tmp/bin/yoke")],
        startup_file="/tmp/.profile", future_adds_bin=True,
        managed_block_present=True,
        future_resolved=[ToolResolution("yoke", "/tmp/bin/yoke")],
        needs_fix=needs_fix, preferred_yoke_path="/tmp/bin/yoke",
    )


def test_path_fix_repairs_once_and_verifies_all_contexts(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        adapter.doctor, "update_shell", lambda: calls.append("repair") or "updated"
    )
    monkeypatch.setattr(
        adapter.doctor,
        "verify_fresh_login",
        lambda: [ToolResolution("yoke", "/tmp/bin/yoke")],
    )
    monkeypatch.setattr(
        adapter.doctor,
        "diagnose",
        diagnosis,
    )
    assert adapter.path_fix(["--yes", "--json"]) == 0
    assert calls == ["repair"]
    assert '"verified": true' in capsys.readouterr().out


def test_path_fix_refuses_failed_non_login_probe(monkeypatch, capsys):
    monkeypatch.setattr(adapter.doctor, "update_shell", lambda: "updated")
    monkeypatch.setattr(
        adapter.doctor,
        "verify_fresh_login",
        lambda: [ToolResolution("yoke", "/tmp/bin/yoke")],
    )
    monkeypatch.setattr(
        adapter.doctor,
        "diagnose",
        lambda: diagnosis(needs_fix=True),
    )
    assert adapter.path_fix(["--yes"]) == 1
    assert "shell_path_unresolved" in capsys.readouterr().out


@pytest.mark.posix_only(reason="reads POSIX login startup files")
@pytest.mark.parametrize("name", [".zprofile", ".zshenv"])
def test_diagnosis_reports_unreadable_startup_without_overruling_probes(
    name, tmp_path, monkeypatch
):
    startup = tmp_path / name
    startup.touch()
    read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path == startup:
            raise PermissionError(errno.EPERM, "Operation not permitted")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    doctor = adapter.doctor
    env = {"HOME": str(tmp_path), "SHELL": "/bin/zsh", "PATH": "/usr/bin:/bin"}
    launcher = str(tmp_path / ".local/bin/yoke")
    monkeypatch.setattr(
        doctor, "_verify_shell", lambda *args, **kwargs: [ToolResolution("yoke", launcher)]
    )

    diag = doctor.diagnose(env=env)

    assert not diag.needs_fix
    assert diag.startup_read_error.startswith(f"{startup}: [Errno 1]")
    assert adapter._diagnosis_json(diag)["startup_read_error"] == diag.startup_read_error
    assert f"startup file  : unreadable ({diag.startup_read_error})" in adapter._render_diagnosis(diag)


@pytest.mark.posix_only(reason="applies POSIX startup file changes")
def test_onboard_apply_excludes_unreadable_startup_file(tmp_path, monkeypatch):
    set_home(monkeypatch, tmp_path)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.delenv("ZDOTDIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    startup = tmp_path / ".zprofile"
    startup.touch()
    read_bytes = Path.read_bytes

    def guarded_read_bytes(path):
        if path == startup:
            raise PermissionError(errno.EPERM, "Operation not permitted")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(adapter.doctor, "diagnose", diagnosis)
    monkeypatch.setattr(adapter.doctor, "verify_fresh_login", lambda *_: [])
    report = {}

    onboard_apply_path.apply({"shell": "zsh", "targets": [{}]}, progress=None, report=report)

    repair = report["path_repair"]
    assert repair["login_verified"]
    assert str(tmp_path / ".zshenv") in repair["changed_files"]
    assert str(startup) not in repair["changed_files"]
    assert f"shell_path_file_skipped: zsh startup file {startup}" in repair["output"]
