"""Portable owner routing preserves standalone and copy-placement behavior."""
from pathlib import Path
import shlex
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts import global_skill_install, owner_private_path
from yoke_cli.config import browser_profile
from yoke_harness import linux_command_custody, linux_platform_payload, linux_desktop_state
from yoke_core.domain import gate_stall_report, process_group_reaping


def test_posix_uid_names_native_windows_recovery(monkeypatch):
    monkeypatch.setattr(owner_private_path, "os", SimpleNamespace(name="nt"))
    with pytest.raises(OSError, match="platform_unsupported.*Windows.*owner predicate"):
        owner_private_path.posix_uid()


@pytest.mark.posix_only(reason="SSH bootstrap executes the POSIX Python interpreter")
def test_remote_program_carries_stdlib_owners_without_installed_yoke():
    command = linux_command_custody._program("print(posix_uid())")
    result = subprocess.run(shlex.split(command), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().isdigit()


@pytest.mark.posix_only(reason="SSH bootstrap executes POSIX process and file-lock boundaries")
def test_desktop_payload_imports_no_installed_yoke_and_embeds_locking(tmp_path):
    source = linux_platform_payload.source() + "\n" + Path(linux_desktop_state.__file__).read_text(encoding="utf-8").replace("from __future__ import annotations", "")
    guard = """import builtins
original_import = builtins.__import__
def stdlib_import(name, *args, **kwargs):
    if name.startswith('yoke_'):
        raise ImportError('package forbidden in standalone payload: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = stdlib_import
"""
    exercise = """
import tempfile, sys
with tempfile.TemporaryFile() as lock:
    acquire_exclusive(lock.fileno())
process = spawn_group_process([sys.executable, '-c', 'pass'])
assert process.wait() == 0
print(posix_uid())
"""
    result = subprocess.run(["/usr/bin/python3", "-I", "-c", guard + source + exercise],
                            capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().isdigit()


def test_global_skill_copy_is_owned_and_refreshed(tmp_path, monkeypatch):
    placement = tmp_path / "placement"
    owned = set()
    def record(path, result, parents=()):
        owned.add(str(path))
        return True
    monkeypatch.setattr(global_skill_install, "_record", record)
    result = global_skill_install.GlobalSkillResult()
    assert global_skill_install._install_folder(placement, "first", owned, result)
    assert global_skill_install._is_current(placement, "first")
    assert not global_skill_install._is_current(placement, "second")
    assert global_skill_install._install_folder(placement, "second", owned, result)
    assert (placement / "SKILL.md").read_text(encoding="utf-8") == "second"
    owned.clear()
    assert not global_skill_install._install_folder(placement, "third", owned, result)
    assert result.reason == global_skill_install.NOT_OWNED


def test_live_profile_uses_authoritative_store_and_refuses_linked_root(tmp_path, monkeypatch):
    store = tmp_path / "live"
    target = store / "project" / "identity"
    legacy = tmp_path / "legacy"
    monkeypatch.setattr(browser_profile, "live_identity_store_root", lambda: store)
    monkeypatch.setattr(browser_profile, "_profile_path", lambda *args: target)
    monkeypatch.setattr(browser_profile, "_legacy_profile_path", lambda *args: legacy)
    path = browser_profile._resolve("project", "identity", create=True)
    assert path == target
    assert path.is_dir()
    assert not browser_profile.is_link(path)
    (path / "cookies").write_text("signed-in", encoding="utf-8")
    assert browser_profile._resolve("project", "identity", create=False) == path
    assert (path / "cookies").read_text(encoding="utf-8") == "signed-in"
    assert not legacy.exists()
    monkeypatch.setattr(browser_profile, "is_link", lambda candidate: candidate == store)
    with pytest.raises(browser_profile.BrowserIdentityError, match="browser_identity_store_unavailable.*link"):
        browser_profile._resolve("project", "identity", create=True)


def test_tree_observers_use_portable_parent_and_command_snapshots(monkeypatch):
    snapshot = [SimpleNamespace(pid=10, ppid=1, cmdline=("runner",)),
                SimpleNamespace(pid=11, ppid=10, cmdline=("child", "argument")),
                SimpleNamespace(pid=12, ppid=11, cmdline=("grandchild",))]
    monkeypatch.setattr(process_group_reaping, "process_command_lines", lambda: snapshot)
    monkeypatch.setattr(gate_stall_report, "process_command_lines", lambda: snapshot)
    assert process_group_reaping.descendant_pids(10) == [11, 12]
    assert gate_stall_report.ancestor_pids(12) == [11, 10, 1]
    assert gate_stall_report._command_for_pid(11) == "child argument"
