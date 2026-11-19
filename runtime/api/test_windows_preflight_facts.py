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
from yoke_contracts.windows_preflight import verdicts


pytestmark = pytest.mark.windows


def test_nul_git_paths_are_utf8_not_utf16(monkeypatch):
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="dir/José\0a\0".encode()),
    )
    assert collector._run(["git", "ls-files", "-z"], []) == "dir/José\0a\0"


@pytest.mark.parametrize("executable", ["wsl.exe", "wevtutil.exe"])
def test_windows_unicode_tool_output_decodes(monkeypatch, executable):
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout="Ubuntu-é\r\n".encode("utf-16-le")
        ),
    )
    assert collector._run([executable], []) == "Ubuntu-é\r\n"


def test_native_tool_failure_keeps_the_windows_reason(monkeypatch):
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=5, stdout=b"", stderr="Access denied: 東京".encode("utf-16-le")
        ),
    )
    errors = []
    assert collector._run(["wevtutil.exe"], errors) == ""
    assert errors == ["wevtutil.exe exited 5: Access denied: 東京"]


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


def test_policy_userdata_keeps_unicode_file_and_event_identity(monkeypatch):
    xml = (
        '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">'
        "<System><EventID>8004</EventID><EventRecordID>42</EventRecordID></System>"
        '<UserData><RuleAndFileData xmlns="http://schemas.microsoft.com/schemas/event/Microsoft.Windows/1.0.0.0">'
        "<FilePath>C:/Users/José 東京/yoke/uv.exe</FilePath><RuleName>Company executable rule</RuleName>"
        "</RuleAndFileData></UserData></Event>"
    )

    def run(argv, errors):
        assert "/uni:true" in argv
        return xml

    monkeypatch.setattr(collector, "_run", run)
    errors = []
    blocks = collector._policy_blocks(errors)
    assert not errors
    assert len(blocks) == 2
    assert blocks[0]["file"] == "C:/Users/José 東京/yoke/uv.exe"
    assert "8004, record 42" in blocks[0]["evidence"]
    assert "Company executable rule" in blocks[0]["evidence"]


@pytest.mark.parametrize("present", [True, False])
def test_vc_runtime_fact_reads_system32(monkeypatch, present):
    seen = []

    def isfile(path):
        seen.append(path)
        return present

    monkeypatch.setattr(collector.os.path, "isfile", isfile)
    expected = ntpath.join("D:\\Win", "System32", "vcruntime140.dll")
    assert collector._vc_runtime({"SystemRoot": "D:\\Win"}) == (
        expected if present else None
    )
    assert seen == [expected]


class _Lxss:
    """A fake winreg whose Lxss key holds ``distributions`` subkeys, or is absent."""

    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER = 1, 2

    def __init__(self, distributions):
        self.distributions = distributions

    def OpenKey(self, root, key):
        assert root == self.HKEY_CURRENT_USER and key.endswith("\\Lxss")
        if self.distributions is None:
            raise FileNotFoundError(key)
        return nullcontext(self)

    def QueryInfoKey(self, opened):
        return (self.distributions, 0, 0)


def _windows_host(monkeypatch, *, build="26200", product="Windows 11 Pro", lxss=1):
    """Stub a Windows host's facts; returns the list every probe argv lands in."""
    monkeypatch.setitem(sys.modules, "winreg", _Lxss(lxss))
    values = {
        "CurrentBuildNumber": build,
        "ProductName": product,
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
    monkeypatch.setattr(collector, "_vc_runtime", lambda env: "vcruntime140.dll")

    def head(request, timeout):
        assert request.get_method() == "HEAD" and timeout == 2
        if "npmjs" in request.full_url:
            raise urllib.error.URLError("blocked")
        return nullcontext()

    monkeypatch.setattr(collector.urllib.request, "urlopen", head)
    return calls


@pytest.mark.parametrize(
    "build,product,edition",
    [
        ("26200", "Windows 10 Enterprise", "Windows 11 Enterprise"),
        ("19045", "Windows 10 Pro", "Windows 10 Pro"),
    ],
)
def test_windows_collection_is_read_only_and_reports_real_probe_results(
    monkeypatch, tmp_path, build, product, edition
):
    calls = _windows_host(monkeypatch, build=build, product=product)
    result = collector.collect_facts(home=tmp_path / "absent", repo=tmp_path)
    assert result["build"] == int(build) and result["store_blocked"]
    assert result["edition"] == edition
    codes = {r["code"]: r for r in verdicts(result)}
    assert "windows_version" not in codes
    coverage = codes["windows_coverage_untested"]
    assert coverage["severity"] == "warning"
    assert coverage["message"].startswith(f"{edition} build {build}")
    assert result["wsl_yoke"] and result["desktop"] and result["browser"]
    assert result["vc_runtime"] == "vcruntime140.dll"
    assert result["blocked_hosts"] == ["registry.npmjs.org (URLError)"]
    assert not (tmp_path / "absent").exists()
    assert any("--running" in argv for argv in calls)
    assert not any("--install" in argv for argv in calls)
    assert any("Stopped WSL distributions" in e for e in result["probe_errors"])


@pytest.mark.parametrize("lxss", [None, 0])
def test_wsl_stub_without_a_registered_distribution_is_not_probed(
    monkeypatch, tmp_path, lxss
):
    """Windows 11's wsl.exe stub exits non-zero with no WSL: that is absence, not a failed probe."""
    calls = _windows_host(monkeypatch, lxss=lxss)
    result = collector.collect_facts(home=tmp_path / "absent", repo=tmp_path)
    assert not any(argv[0] == "wsl.exe" for argv in calls)
    assert not any("wsl" in e.lower() for e in result["probe_errors"])
    assert not result["wsl_yoke"]
    assert not any(r["code"] == "probe_incomplete" for r in verdicts(result))
