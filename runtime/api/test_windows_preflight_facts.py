"""Exercise Windows probes on every OS without starting tools or writing state."""

from __future__ import annotations

from contextlib import nullcontext
import ctypes
import ntpath
import subprocess
import sys
from types import SimpleNamespace
import urllib.error

import pytest

from yoke_contracts import windows_preflight_facts as collector


def test_nul_git_paths_are_utf8_not_utf16(monkeypatch):
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="dir/José\0a\0".encode()),
    )
    assert collector._run(["git", "ls-files", "-z"], []) == "dir/José\0a\0"


def test_wsl_unicode_distribution_names_decode(monkeypatch):
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout="Ubuntu-é\r\n".encode("utf-16-le")
        ),
    )
    assert collector._run(["wsl.exe", "--list"], []) == "Ubuntu-é\r\n"


@pytest.mark.parametrize(
    "failure", [OSError("denied"), subprocess.TimeoutExpired("git", 4)]
)
def test_probe_failure_is_named(monkeypatch, failure):
    def fail(*a, **kw):
        raise failure

    monkeypatch.setattr(collector.subprocess, "run", fail)
    errors = []
    assert collector._run(["git"], errors) == ""
    assert errors and "git" in errors[0]


@pytest.mark.parametrize(
    "path,env,drive,fs,kind",
    [
        (
            "C:/Users/A/OneDrive/.yoke",
            {"OneDrive": "C:/Users/A/OneDrive"},
            3,
            "NTFS",
            "onedrive",
        ),
        (
            "C:/Users/A/AppData/Roaming/yoke",
            {"APPDATA": "C:/Users/A/AppData/Roaming"},
            3,
            "NTFS",
            "roaming",
        ),
        ("Z:/yoke", {}, 4, "NTFS", "network"),
        ("D:/yoke", {"OneDrive": "C:/cloud"}, 3, "exFAT", "local"),
    ],
)
def test_storage_reads_drive_and_profile_facts(monkeypatch, path, env, drive, fs, kind):
    def volume(root, label, size, serial, maximum, flags, output, length):
        output.value = fs
        return 1

    kernel = SimpleNamespace(
        GetDriveTypeW=lambda root: drive, GetVolumeInformationW=volume
    )
    monkeypatch.setattr(
        collector,
        "ctypes",
        SimpleNamespace(
            create_unicode_buffer=ctypes.create_unicode_buffer,
            windll=SimpleNamespace(kernel32=kernel),
        ),
    )
    monkeypatch.setattr(
        collector, "os", SimpleNamespace(path=SimpleNamespace(realpath=ntpath.normpath))
    )
    assert collector._storage(path, env, []) == {
        "path": path,
        "kind": kind,
        "filesystem": fs,
    }


def test_policy_events_keep_enforced_block_file_and_policy(monkeypatch):
    xml = (
        '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">'
        '<EventData><Data Name="FileName">C:/yoke/python.exe</Data>'
        '<Data Name="PolicyName">Corporate policy</Data></EventData></Event>'
    )
    monkeypatch.setattr(collector, "_run", lambda *a: xml)
    blocks = collector._policy_blocks([])
    assert len(blocks) == 2
    assert all(
        b["file"] == "C:/yoke/python.exe" and "Corporate policy" in b["evidence"]
        for b in blocks
    )


def test_bad_policy_log_is_not_clean_evidence(monkeypatch):
    monkeypatch.setattr(collector, "_run", lambda *a: "bad xml")
    errors = []
    assert collector._policy_blocks(errors) == []
    assert len(errors) == 2


def test_windows_collection_is_read_only_and_reports_real_probe_results(
    monkeypatch, tmp_path
):
    monkeypatch.setitem(
        sys.modules,
        "winreg",
        SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2),
    )
    values = {
        "CurrentBuildNumber": "26100",
        "ProductName": "Windows 11 Enterprise",
        "LongPathsEnabled": 0,
        "ProgId": "browser",
        "RemoveWindowsStore": 1,
    }
    monkeypatch.setattr(
        collector,
        "_registry",
        lambda root, key, name, errors, default=None: values.get(name, default),
    )
    monkeypatch.setattr(
        collector,
        "platform",
        SimpleNamespace(system=lambda: "Windows", machine=lambda: "AMD64"),
    )
    monkeypatch.setattr(
        collector,
        "ctypes",
        SimpleNamespace(
            windll=SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 0))
        ),
    )
    monkeypatch.setattr(
        collector,
        "_storage",
        lambda path, env, errors: {"path": path, "kind": "local", "filesystem": "NTFS"},
    )
    monkeypatch.setattr(collector.shutil, "which", lambda tool: tool + ".exe")
    monkeypatch.setenv("SESSIONNAME", "Console")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    calls = []

    def run(argv, errors):
        calls.append(argv)
        if "--running" in argv:
            return "Ubuntu-é\n"
        if "--distribution" in argv:
            return "/home/user/.local/bin/yoke\n"
        return ""

    monkeypatch.setattr(collector, "_run", run)
    monkeypatch.setattr(collector, "_policy_blocks", lambda errors: [])

    def head(request, timeout):
        assert request.get_method() == "HEAD" and timeout == 2
        if "npmjs" in request.full_url:
            raise urllib.error.URLError("blocked")
        return nullcontext()

    monkeypatch.setattr(collector.urllib.request, "urlopen", head)
    result = collector.collect_facts(home=tmp_path / "absent", repo=tmp_path)
    assert result["build"] == 26100 and result["store_blocked"]
    assert result["wsl_yoke"] and result["desktop"] and result["browser"]
    assert result["blocked_hosts"] == ["registry.npmjs.org (URLError)"]
    assert not (tmp_path / "absent").exists()
    assert any("--running" in argv for argv in calls)
    assert not any("--install" in argv for argv in calls)
