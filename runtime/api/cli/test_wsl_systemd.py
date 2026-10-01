"""WSL configuration preservation and every automatic privilege path."""

import subprocess

import pytest

from yoke_harness import wsl_systemd as wsl
from yoke_cli.commands.adapters import wsl as adapter


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[network]\nhostname=machine\n",
        "# user settings\n[boot]\ncommand=echo hello\nsystemd=false\n\n[user]\ndefault=me\n",
        "[boot]\ncommand=echo hello\n[network]\nhostname=machine",
        "[boot]\nsystemd = false # old setting\n",
    ],
)
def test_enable_preserves_unrelated_settings_and_is_idempotent(text):
    updated = wsl.enabled_config(text)
    assert wsl._enabled(updated)
    assert wsl.enabled_config(updated) == updated
    for line in text.splitlines():
        if "systemd" not in line and line:
            assert line in updated


def test_enabled_config_is_unchanged():
    text = "[boot]\nsystemd=true\n# keep my formatting\n"
    assert wsl.enabled_config(text) == text


@pytest.mark.parametrize("text", ["not ini", "[boot]\nsystemd=false\nsystemd=true"])
def test_invalid_config_teaches_repair(text):
    with pytest.raises(
        RuntimeError,
        match="wsl_config_invalid.*",
    ):
        wsl.enabled_config(text)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    config = tmp_path / "wsl.conf"
    monkeypatch.setattr(wsl, "CONFIG_PATH", config)
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    monkeypatch.setattr(wsl, "systemd_running", lambda: False)
    monkeypatch.setattr(
        wsl, "_enable", lambda: config.write_text("[boot]\nsystemd=true\n")
    )
    return config


def test_non_wsl_never_probes_or_writes(monkeypatch):
    monkeypatch.setattr(wsl, "is_wsl", lambda: False)
    monkeypatch.setattr(wsl, "systemd_running", lambda: pytest.fail("not WSL"))
    assert wsl.setup() == "not_wsl"


def test_running_systemd_needs_no_config_access(setup, monkeypatch):
    monkeypatch.setattr(wsl, "systemd_running", lambda: True)
    monkeypatch.setattr(wsl, "_read", lambda path: pytest.fail("already running"))
    assert wsl.setup(emit=lambda message: None) == "already_running"


def test_pending_restart_needs_no_privilege(setup, monkeypatch):
    setup.write_text("[boot]\nsystemd=true\n")
    monkeypatch.setattr(
        wsl, "command_authority", lambda message: pytest.fail("already enabled")
    )
    logs = []
    assert wsl.setup(emit=logs.append) == "restart_required"
    assert "wsl --shutdown" in logs[-1]


@pytest.mark.parametrize(
    "prefix,interactive",
    [([], False), (["sudo", "-n", "--"], False), (["sudo", "--"], True)],
)
def test_root_passwordless_and_interactive_paths(
    setup, monkeypatch, prefix, interactive
):
    monkeypatch.setattr(wsl, "command_authority", lambda message: (prefix, interactive))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        setup.write_text("[boot]\nsystemd=true\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wsl.subprocess, "run", run)
    assert wsl.setup(emit=lambda message: None) == "restart_required"
    if prefix:
        assert calls[0][0][: len(prefix)] == prefix
        assert calls[0][0][-2:] == ["yoke_harness.wsl_systemd", "--enable"]
        assert calls[0][1]["capture_output"] is not interactive
        assert "stdin" not in calls[0][1]
        assert len(calls) == 1
    else:
        assert not calls


def test_no_authority_reports_reason_and_recovery(setup, monkeypatch):
    def unavailable(message):
        raise RuntimeError(message)

    monkeypatch.setattr(wsl, "command_authority", unavailable)
    with pytest.raises(
        RuntimeError, match="wsl_systemd_authority_unavailable.*yoke wsl setup"
    ):
        wsl.setup()
    assert not setup.exists()


def test_failed_privileged_write_never_reports_enabled(setup, monkeypatch):
    monkeypatch.setattr(
        wsl, "command_authority", lambda message: (["sudo", "--"], True)
    )
    monkeypatch.setattr(
        wsl.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(command, 1, None, None),
    )
    logs = []
    with pytest.raises(RuntimeError, match="wsl_systemd_enable_failed"):
        wsl.setup(emit=logs.append)
    assert not logs


def test_success_requires_readback(setup, monkeypatch):
    monkeypatch.setattr(wsl, "command_authority", lambda message: ([], False))
    monkeypatch.setattr(wsl, "_enable", lambda: None)
    with pytest.raises(RuntimeError, match="wsl_systemd_enable_unverified"):
        wsl.setup()


def test_unlaunchable_privileged_writer_teaches_recovery(setup, monkeypatch):
    monkeypatch.setattr(
        wsl, "command_authority", lambda message: (["sudo", "--"], True)
    )

    def unavailable(command, **kwargs):
        raise FileNotFoundError("sudo unavailable")

    monkeypatch.setattr(wsl.subprocess, "run", unavailable)
    with pytest.raises(RuntimeError, match="wsl_systemd_enable_failed.*yoke wsl setup"):
        wsl.setup()


def test_atomic_write_preserves_mode_and_settings(tmp_path):
    config = tmp_path / "wsl.conf"
    config.write_text("[network]\nhostname=example\n")
    config.chmod(0o640)
    wsl._enable(config)
    assert wsl._enabled(config.read_text())
    assert "hostname=example" in config.read_text()
    assert config.stat().st_mode & 0o777 == 0o640


def test_atomic_write_creates_missing_config(tmp_path):
    config = tmp_path / "wsl.conf"
    wsl._enable(config)
    assert wsl._enabled(config.read_text())
    assert config.stat().st_mode & 0o777 == 0o644


def test_failed_atomic_write_preserves_config_and_cleans_temporary_file(
    tmp_path, monkeypatch
):
    config = tmp_path / "wsl.conf"
    original = "[boot]\nsystemd=false\n"
    config.write_text(original)

    def refused(*args):
        raise PermissionError("write denied")

    monkeypatch.setattr(wsl.os, "replace", refused)
    with pytest.raises(RuntimeError, match="wsl_config_write_failed.*yoke wsl setup"):
        wsl._enable(config)
    assert config.read_text() == original
    assert list(tmp_path.iterdir()) == [config]


def test_unreadable_proc_reports_recovery(setup, monkeypatch):
    def unreadable():
        raise PermissionError("proc blocked")

    monkeypatch.setattr(wsl, "systemd_running", unreadable)
    with pytest.raises(RuntimeError, match="wsl_pid1_unreadable.*restore /proc"):
        wsl.setup()


def test_symlink_is_refused_without_modifying_target(tmp_path):
    target = tmp_path / "target"
    target.write_text("[boot]\nsystemd=false\n")
    config = tmp_path / "wsl.conf"
    config.symlink_to(target)
    with pytest.raises(RuntimeError, match="wsl_config_symlink"):
        wsl._enable(config)
    assert "false" in target.read_text()


def test_cli_reports_named_setup_failure(monkeypatch, capsys):
    def failure():
        raise RuntimeError("wsl_config_write_failed: recovery step")

    monkeypatch.setattr(adapter, "setup", failure)
    assert adapter.wsl_setup([]) == 1
    assert "wsl_config_write_failed" in capsys.readouterr().err
