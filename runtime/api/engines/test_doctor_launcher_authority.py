"""Launcher authority uses the actual native Windows PATH winners."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_cli.config import path_doctor
from yoke_core.engines import doctor_hc_launcher_authority as doctor


@pytest.fixture
def native_windows(tmp_path, monkeypatch):
    launcher = tmp_path / "bin" / "yoke.cmd"
    launcher.parent.mkdir()
    launcher.touch()
    launcher.with_name("yoke").touch()  # The installed POSIX companion is legitimate.

    def configure(*, login=None, current=None, repair=False):
        monkeypatch.setattr(doctor, "_WINDOWS", True)
        monkeypatch.setattr(doctor, "_resolve_checkout", lambda _args: tmp_path)
        for name in (
            "_login_shell_yoke", "canonical_shim_path",
            "enumerate_shadow_installs", "converge_machine",
        ):
            monkeypatch.setattr(doctor, name, Mock(side_effect=AssertionError(name)))
        monkeypatch.setattr(
            path_doctor,
            "diagnose",
            lambda **_kw: SimpleNamespace(
                preferred_yoke_path=str(launcher),
                future_resolved=[path_doctor.ToolResolution("yoke", login)],
                current_resolved=[path_doctor.ToolResolution("yoke", current)],
                contexts=(),
            ),
        )
        version_probe = Mock(return_value=None)
        path_repair = Mock()
        monkeypatch.setattr(doctor, "_release_problem", version_probe)
        monkeypatch.setattr(path_doctor, "update_shell", path_repair)
        collector = Mock()
        doctor.hc_launcher_authority(None, SimpleNamespace(fix=repair), collector)
        return collector.record.call_args.args[2:], version_probe, path_repair

    return launcher, configure


def test_canonical_windows_cmd_passes_and_uses_native_path_repair(native_windows):
    launcher, configure = native_windows
    (severity, detail), version_probe, path_repair = configure(
        login=str(launcher), current=str(launcher), repair=True
    )
    assert severity == "PASS"
    assert str(launcher) in detail
    assert version_probe.call_args.args[0] == str(launcher)
    path_repair.assert_called_once()


@pytest.mark.parametrize("login", [None, "shadow/yoke.exe"])
def test_missing_or_shadowing_windows_launcher_fails(native_windows, login):
    launcher, configure = native_windows
    (severity, detail), version_probe, path_repair = configure(
        login=login, current=str(launcher)
    )
    assert severity == "FAIL"
    assert "fresh Windows PATH resolved" in detail
    assert "yoke path fix --yes" in detail
    assert (login or "no yoke") in detail
    version_probe.assert_not_called()
    path_repair.assert_not_called()
