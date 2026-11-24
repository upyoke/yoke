"""Bash spelling and native client identity share one path resolver."""

import os
import subprocess
from types import SimpleNamespace

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
    paths._mount_path.cache_clear()
    monkeypatch.setattr(paths, "git_cygpath", lambda: "C:/Git/usr/bin/cygpath.exe")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "C:\\Git\\usr\\bin\n", "")

    monkeypatch.setattr(paths.subprocess, "run", run)
    assert paths._mount_path("/usr/bin") == "C:\\Git\\usr\\bin"
    assert calls == [["C:/Git/usr/bin/cygpath.exe", "-w", "--", "/usr/bin"]]
    paths._mount_path.cache_clear()


def test_unnameable_windows_operand_keeps_its_mount_path(monkeypatch):
    monkeypatch.setattr(paths, "os", SimpleNamespace(name="nt"))
    filename = "x" * 300 + ".md"
    converted = []

    def mount_path(path):
        converted.append(path)
        if path == "/":
            return r"C:\Git"
        raise paths.BashPathResolutionError("cygpath rejected the operand")

    monkeypatch.setattr(paths, "_mount_path", mount_path)
    assert paths.resolve_bash_path("/" + filename, home="C:/home", canonical=False) == (
        "C:\\Git\\" + filename
    )
    assert converted == ["/" + filename, "/"]

    with pytest.raises(paths.BashPathResolutionError, match="cygpath rejected"):
        paths.resolve_bash_path("/ordinary", home="C:/home", canonical=False)
    assert converted[-1] == "/ordinary"


@pytest.mark.windows_only(reason="real Git for Windows mount table")
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


@pytest.mark.windows_only(reason="Windows short-name filesystem aliases")
def test_windows_short_names_canonicalize_on_both_sides(tmp_path):
    import ctypes

    long_path = tmp_path / "directory with long name"
    long_path.mkdir()
    buffer = ctypes.create_unicode_buffer(32768)
    assert ctypes.windll.kernel32.GetShortPathNameW(str(long_path), buffer, len(buffer))
    assert paths.canonical_native_path(buffer.value) == paths.canonical_native_path(
        str(long_path)
    )


def test_relayed_windows_paths_use_only_client_observations(monkeypatch):
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
        from yoke_core.domain.lint_session_cwd_target_extract import _resolve_target_paths

        assert _resolve_target_paths(["/tmp"], "") == [r"C:\Users\runner\Temp"]
        assert paths.resolve_bash_path("/tmp", "D:/repo") == r"C:\Users\runner\Temp"
        assert paths.resolve_bash_path("/c/repo", "D:/repo") == r"C:\repo"
        assert (
            paths.resolve_bash_path("../file", "C:/Users/RUNNER~1/repo")
            == r"C:\Users\runner\file"
        )
        assert paths.resolve_bash_path("/tmp", "D:/repo", shell="powershell").replace("\\", "/") == "D:/tmp"
        assert paths.join_path("D:/repo", "/sub", shell="powershell").replace("\\", "/") == "D:/sub"
        with pytest.raises(ValueError, match="git_bash_client_path_required"):
            paths.resolve_bash_path("/unobserved", "D:/repo")
        def no_authority_cwd():
            raise AssertionError("authority cwd is not client evidence")

        with monkeypatch.context() as patch:
            patch.setattr(paths.os, "getcwd", no_authority_cwd)
            assert paths.resolve_bash_path("C:/repo/file", shell="powershell") == r"C:\repo\file"
            with pytest.raises(ValueError, match="git_bash_client_cwd_required"):
                paths.resolve_bash_path("/tmp", shell="powershell")

    resolve(payload)
    assert paths.join_path("/repo", "file") == "/repo/file"


def test_posix_client_aliases_resolve_before_parent_hops_and_keep_case():
    from yoke_contracts.hook_runner.client_facts import client_fact, WRITE_TARGETS_KEY

    payload = client_fact(
        WRITE_TARGETS_KEY,
        {
            "bash_paths": {
                "windows": False,
                "home": "/client/home",
                "canonical": {"/tmp/link": "/repo/sub"},
            }
        },
    )

    @paths.with_client_paths
    def resolve(payload):
        assert paths.resolve_bash_path("/tmp/link/../file") == "/repo/file"
        assert paths.resolve_bash_path("/TMP/link/../file") == "/TMP/file"
        assert paths.resolve_bash_path("~/file") == "/client/home/file"

    resolve(payload)


def test_windows_home_facts_validate_on_a_posix_authority():
    from yoke_contracts.hook_runner.client_facts import client_fact, WRITE_TARGETS_KEY
    from yoke_contracts.hook_runner.session_cwd import (
        client_machine_home_fact,
        client_machine_home,
    )

    payload = client_fact(
        WRITE_TARGETS_KEY,
        {
            "bash_paths": {
                "windows": True,
                "canonical": {},
                "mount_paths": {},
            }
        },
    )

    @paths.with_client_paths
    def validate(payload):
        native_home = "C:/Users/operator"
        home_fact = client_machine_home_fact(native_home)
        assert client_machine_home(home_fact) == native_home
        assert client_machine_home_fact("C:/") == {}

    validate(payload)


def test_temp_filter_normalizes_parent_hops_and_client_aliases():
    from yoke_core.domain.path_claim_bash_parser import _is_tmp_path

    with paths.client_path_scope({"windows": False, "canonical": {"/tmp/link": "/repo"}}):
        assert _is_tmp_path("/tmp/scratch.txt")
        assert not _is_tmp_path("/tmp/../repo/source.py")
        assert not _is_tmp_path("/tmp/link/source.py")
