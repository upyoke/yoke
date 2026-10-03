"""Windows lifetime convergence, configuration preservation, and refusal paths."""

import subprocess

import pytest

from yoke_harness import wsl_lifetime as lifetime


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[wsl2]\nmemory=8GB\nkernel=C:\\custom\\kernel\n",
        "# keep\r\n[general]\r\ninstanceIdleTimeout = 15000 ; old\r\n[wsl2]\r\nmemory=8GB\r\n",
        "[general]\ndistributionInstallPath=C:\\WSL\n[wsl2]\nmemory=8GB",
        "[general]\ndistributionInstallPath=C:\\WSL",
        "[General]\nINSTANCEIDLETIMEOUT=15000\n",
    ],
)
def test_lifetime_preserves_other_settings_and_is_idempotent(text):
    updated = lifetime.enabled_config(text)
    assert "-1" in updated
    assert lifetime.enabled_config(updated) == updated
    for line in text.splitlines():
        if "instanceidletimeout" not in line.lower():
            assert line in updated
    if "\r\n" in text:
        assert "\n" not in updated.replace("\r\n", "")
        assert "; old" in updated


def test_enabled_config_keeps_exact_bytes():
    text = "[general]\ninstanceIdleTimeout = -1 ; keep\n"
    assert lifetime.enabled_config(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "not ini",
        "[general]\ninstanceIdleTimeout=1\ninstanceIdleTimeout=2",
        "[general]\n[General]\n",
    ],
)
def test_invalid_ini_refuses_with_recovery(text):
    with pytest.raises(
        RuntimeError, match="(?s)wsl_lifetime_config_invalid.*rerun yoke wsl setup"
    ):
        lifetime.enabled_config(text)


@pytest.mark.parametrize(
    "encoding,bom",
    [
        ("utf-8", ""),
        ("utf-8", "\ufeff"),
        ("utf-16-le", "\ufeff"),
        ("utf-16-be", "\ufeff"),
    ],
)
def test_atomic_write_preserves_encoding_comments_and_newlines(tmp_path, encoding, bom):
    path = tmp_path / ".wslconfig"
    original = (
        bom
        + "[wsl2]\r\nmemory=8GB\r\n# keep\r\n[general]\r\ninstanceIdleTimeout=15000\r\n"
    )
    path.write_bytes(original.encode(encoding))
    path.chmod(0o640)
    assert lifetime._enable(path)
    updated = path.read_bytes()
    assert updated.decode(encoding).startswith(
        bom + "[wsl2]\r\nmemory=8GB\r\n# keep\r\n"
    )
    assert "instanceIdleTimeout=-1\r\n" in updated.decode(encoding)
    assert path.stat().st_mode & 0o777 == 0o640
    assert not lifetime._enable(path)
    assert path.read_bytes() == updated


def test_missing_config_is_created(tmp_path):
    path = tmp_path / ".wslconfig"
    assert lifetime._enable(path)
    assert "[general]\ninstanceIdleTimeout=-1" in path.read_text()


def test_failed_write_preserves_config(tmp_path, monkeypatch):
    path = tmp_path / ".wslconfig"
    original = "[wsl2]\nmemory=8GB\n"
    path.write_text(original)

    def denied(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(lifetime.os, "replace", denied)
    with pytest.raises(
        RuntimeError, match="wsl_lifetime_config_write_failed.*rerun yoke wsl setup"
    ):
        lifetime._enable(path)
    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path]


def test_symlink_never_changes_target(tmp_path):
    target = tmp_path / "target"
    target.write_text("[general]\ninstanceIdleTimeout=15000\n")
    path = tmp_path / ".wslconfig"
    path.symlink_to(target)
    with pytest.raises(RuntimeError, match="wsl_lifetime_config_symlink"):
        lifetime._enable(path)
    assert "15000" in target.read_text()


@pytest.mark.parametrize("version", ["WSL version: 2.5.4.0", "Version WSL : 3.0.1.0"])
def test_supported_versions_and_localized_label(monkeypatch, version):
    monkeypatch.setattr(lifetime, "_windows_command", lambda name: name)
    monkeypatch.setattr(
        lifetime, "_run", lambda command: version + "\nKernel version: 6.6.0"
    )
    lifetime._check_version()


@pytest.mark.parametrize(
    "version,reason",
    [
        ("WSL version: 2.5.3.0", "wsl_lifetime_version_unsupported"),
        ("unknown\nKernel version: 6.6.0", "wsl_version_unreadable"),
    ],
)
def test_version_refusal_never_reads_or_writes_profile(monkeypatch, version, reason):
    monkeypatch.setattr(lifetime, "_windows_command", lambda name: name)
    monkeypatch.setattr(lifetime, "_run", lambda command: version)
    monkeypatch.setattr(
        lifetime, "_config_path", lambda: pytest.fail("unsupported version")
    )
    with pytest.raises(RuntimeError, match=reason + ".*wsl --update"):
        lifetime.setup()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le"])
def test_windows_output_encodings(monkeypatch, encoding):
    monkeypatch.setattr(
        lifetime.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(
            command, 0, "WSL version: 3.0.1.0\r\n".encode(encoding), b""
        ),
    )
    assert lifetime._run(["wsl.exe", "--version"]) == "WSL version: 3.0.1.0"


def test_missing_windows_interop_names_recovery(monkeypatch):
    monkeypatch.setattr(lifetime.shutil, "which", lambda name: None)
    with pytest.raises(
        RuntimeError, match="wsl_windows_interop_unavailable.*Enable Windows interop"
    ):
        lifetime._check_version()


def test_windows_timeout_names_recovery(monkeypatch):
    def timeout(command, **kw):
        raise subprocess.TimeoutExpired(command, kw["timeout"])

    monkeypatch.setattr(lifetime.subprocess, "run", timeout)
    with pytest.raises(
        RuntimeError, match="wsl_windows_command_unavailable.*rerun yoke wsl setup"
    ):
        lifetime._run(["wsl.exe"])


def test_profile_uses_windows_owner_and_wslpath_without_shell(tmp_path, monkeypatch):
    calls = []
    profile = r"D:\Users\Person With Spaces"
    monkeypatch.setattr(lifetime, "_windows_command", lambda name: name)

    def run(command):
        calls.append(command)
        return str(tmp_path) if command[0] == "wslpath" else profile

    monkeypatch.setattr(lifetime, "_run", run)
    assert lifetime._config_path() == tmp_path / ".wslconfig"
    assert calls[1] == ["wslpath", "-u", profile]
    assert "GetFolderPath('UserProfile')" in calls[0][-1]


@pytest.mark.parametrize("profile", ["", "relative", "C:\\Users\\me\nC:\\Users\\other"])
def test_bad_profile_is_refused(monkeypatch, profile):
    monkeypatch.setattr(lifetime, "_windows_command", lambda name: name)
    monkeypatch.setattr(lifetime, "_run", lambda command: profile)
    with pytest.raises(RuntimeError, match="wsl_windows_profile_unavailable"):
        lifetime._config_path()


def test_setup_reports_change_and_restart(tmp_path, monkeypatch):
    path = tmp_path / ".wslconfig"
    monkeypatch.setattr(lifetime, "_check_version", lambda: None)
    monkeypatch.setattr(lifetime, "_config_path", lambda: path)
    logs = []
    assert lifetime.setup(emit=logs.append)
    assert "restart is required" in logs[-1]
    assert not lifetime.setup(emit=logs.append)
    assert "already disabled" in logs[-1]
