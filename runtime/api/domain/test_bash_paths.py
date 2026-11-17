"""Bash spelling and native client identity share one path resolver."""

import os
import subprocess

import pytest

from yoke_contracts.hook_runner import bash_paths as paths
from yoke_contracts.hook_runner.shell_parse import parse_shell


def test_drive_paths_do_not_join_to_the_authority_filesystem():
    assert paths.join_path("C:/repo", "D:/lane") == "D:/lane"
    assert (
        paths.join_path("C:/repo", "sub/file").replace("\\", "/") == "C:/repo/sub/file"
    )
    assert (
        paths.canonical_native_path("C:/repo/../lane").replace("\\", "/") == "C:/lane"
    )


def test_native_backslashes_keep_their_bash_escape_meaning():
    assert parse_shell(r"touch C:\Users\x").segments[0].argv == ("touch", "C:Usersx")
    assert parse_shell('touch "C:/Users/x"').segments[0].argv == ("touch", "C:/Users/x")


def test_missing_git_for_windows_names_recovery(monkeypatch):
    paths.git_cygpath.cache_clear()
    monkeypatch.setattr(paths.shutil, "which", lambda _: None)
    monkeypatch.setattr(paths.os, "environ", {})
    with pytest.raises(
        ValueError, match="git_bash_unavailable.*install Git for Windows"
    ):
        paths.git_cygpath()
    paths.git_cygpath.cache_clear()


def test_mount_conversion_uses_the_selected_git_installation(monkeypatch):
    monkeypatch.setattr(paths, "git_cygpath", lambda: "C:/Git/usr/bin/cygpath.exe")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "C:\\Git\\usr\\bin\n", "")

    monkeypatch.setattr(paths.subprocess, "run", run)
    assert paths._mount_path("/usr/bin") == "C:\\Git\\usr\\bin"
    assert calls == [["C:/Git/usr/bin/cygpath.exe", "-w", "--", "/usr/bin"]]


@pytest.mark.skipif(os.name != "nt", reason="real Git for Windows mount table")
@pytest.mark.parametrize(
    "spelling", ["drive", "git-drive", "home", "relative", "tmp", "dev", "usr"]
)
def test_windows_git_bash_spellings(tmp_path, spelling):
    root = str(tmp_path.resolve())
    operand = {
        "drive": tmp_path.as_posix(),
        "git-drive": "/" + root[0].lower() + root[2:].replace("\\", "/"),
        "home": "~/sub",
        "relative": "sub",
        "tmp": "/tmp",
        "dev": "/dev/null",
        "usr": "/usr/bin",
    }[spelling]
    expected = (
        str(tmp_path / "sub")
        if spelling in {"home", "relative"}
        else root
        if spelling in {"drive", "git-drive"}
        else paths._mount_path(operand)
    )
    assert paths.resolve_bash_path(operand, root, home=root) == os.path.realpath(
        expected
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows short-name filesystem aliases")
def test_windows_short_names_canonicalize_on_both_sides(tmp_path):
    import ctypes

    long_path = tmp_path / "directory with long name"
    long_path.mkdir()
    buffer = ctypes.create_unicode_buffer(32768)
    assert ctypes.windll.kernel32.GetShortPathNameW(str(long_path), buffer, len(buffer))
    assert paths.canonical_native_path(buffer.value) == paths.canonical_native_path(
        str(long_path)
    )


def test_relayed_windows_paths_use_only_client_observations():
    from yoke_contracts.hook_runner.client_facts import client_fact, WRITE_TARGETS_KEY

    payload = client_fact(
        WRITE_TARGETS_KEY,
        {
            "bash_paths": {
                "windows": True,
                "mount_paths": {"/tmp": "C:/Users/runner/Temp", "/c/repo": "C:/repo"},
                "canonical": {"C:/Users/RUNNER~1": "C:/Users/runner"},
            }
        },
    )

    @paths.with_client_paths
    def resolve(payload):
        assert paths.resolve_bash_path("/tmp", "D:/repo") == "C:/Users/runner/Temp"
        assert paths.resolve_bash_path("/c/repo", "D:/repo") == "C:/repo"
        assert (
            paths.resolve_bash_path("../file", "C:/Users/RUNNER~1/repo")
            == "C:/Users/runner/file"
        )
        with pytest.raises(ValueError, match="git_bash_client_path_required"):
            paths.resolve_bash_path("/unobserved", "D:/repo")

    resolve(payload)
    assert paths.join_path("/repo", "file") == "/repo/file"
