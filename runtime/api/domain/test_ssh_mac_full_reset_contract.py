"""Rendered-program contract coverage for dedicated Test Mac reset."""

from __future__ import annotations

from pathlib import Path

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    FakeResetTransport,
    closed_reset_stdout,
    run_zsh_syntax_if_available,
)
from yoke_cli.config import path_doctor
from yoke_core.domain.ssh_mac_full_reset import execute_full_test_mac_reset
from yoke_core.domain.ssh_mac_full_reset_contract import (
    EVIDENCE_SOURCE_PATH,
    FULL_RESET_MARKER,
    FULL_RESET_REMOTE_PATH,
    RESET_TEMP_FILES,
    RETAINED_EVIDENCE_DIRECTORY,
    STARTUP_FILE_NAMES,
    TOKEN_LOCATIONS,
)
from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


def test_remote_program_matches_mac_reset_contract_without_system_wipe() -> None:
    assert STARTUP_FILE_NAMES == tuple(
        str(path.relative_to("/"))
        for path in path_doctor.supported_startup_files(Path("/"))
    )
    assert {
        ".zprofile",
        ".zshenv",
        ".zshrc",
        ".zlogin",
        ".bash_profile",
        ".bashrc",
        ".profile",
    } == set(STARTUP_FILE_NAMES)
    assert RESET_TEMP_FILES == ("/tmp/yoke-install", "/tmp/yoke-token")
    assert {source for source, _backup, _label in TOKEN_LOCATIONS} == {
        "/tmp/yoke-stage.token",
        "/tmp/yoke-prod.token",
    }
    assert path_doctor.MANAGED_BEGIN in FULL_RESET_SCRIPT
    assert path_doctor.MANAGED_END in FULL_RESET_SCRIPT
    assert "uv was installed" in FULL_RESET_SCRIPT
    assert "tool_bin_home_reference=" in FULL_RESET_SCRIPT
    assert "index($0, absolute_bin)" in FULL_RESET_SCRIPT
    assert "for flag in -lic -c" in FULL_RESET_SCRIPT
    assert '"$shell_path" "$flag"' in FULL_RESET_SCRIPT
    assert 'command -v "$tool"' in FULL_RESET_SCRIPT
    assert '/usr/bin/tr ":" "\\n"' in FULL_RESET_SCRIPT
    assert FULL_RESET_MARKER in FULL_RESET_SCRIPT
    assert ".ssh" not in FULL_RESET_SCRIPT
    assert "CommandLineTools" not in FULL_RESET_SCRIPT
    assert "yoke*.log" not in FULL_RESET_SCRIPT
    reap_step = 'run_reset_step "$reset_phase_reap_processes" reap_processes'
    remove_step = (
        'run_reset_step "$reset_phase_remove_registered_state" remove_registered_state'
    )
    assert FULL_RESET_SCRIPT.index(reap_step) < FULL_RESET_SCRIPT.index(remove_step)
    assert "/bin/kill" in FULL_RESET_SCRIPT
    assert "sleep 600" not in FULL_RESET_SCRIPT
    assert "IFS= read -r pid command_line" not in FULL_RESET_SCRIPT
    assert "/bin/ps -ww -u" in FULL_RESET_SCRIPT
    assert "while read -r pid command_line; do" in FULL_RESET_SCRIPT
    assert '(( pid != $$ && ! ${+reaped_seen[$pid]} )) || continue' in FULL_RESET_SCRIPT


def test_reset_rejects_xdg_tool_paths_outside_explicit_test_mac_home() -> None:
    transport = FakeResetTransport("")
    path_state = path_doctor.resolve_path_state_contract(
        env={
            "HOME": "/Users/tester",
            "SHELL": "/bin/zsh",
            "XDG_BIN_HOME": "/opt/yoke/bin",
        }
    )

    result = execute_full_test_mac_reset(
        run_remote=transport.run,
        upload_text=transport.upload,
        home="/Users/tester",
        path_state=path_state,
    )

    assert not result.ok
    assert result.error_code == "unsafe_test_mac_tool_path"
    assert transport.commands == []
    assert transport.uploads == {}


def test_reset_renders_contained_xdg_and_bash_shell_contract() -> None:
    transport = FakeResetTransport(
        closed_reset_stdout(stage="ABSENT", prod="ABSENT", evidence="ABSENT")
    )
    xdg_bin_home = "/Users/tester/Library/Yoke Bin"
    path_state = path_doctor.resolve_path_state_contract(
        env={
            "HOME": "/Users/tester",
            "SHELL": "/bin/bash",
            "XDG_BIN_HOME": xdg_bin_home,
        }
    )

    result = execute_full_test_mac_reset(
        run_remote=transport.run,
        upload_text=transport.upload,
        home="/Users/tester",
        path_state=path_state,
    )

    assert result.ok
    script = transport.uploads[FULL_RESET_REMOTE_PATH]
    syntax = run_zsh_syntax_if_available(script)
    if syntax is not None:
        assert syntax.returncode == 0, syntax.stderr
    assert "shell_path=/bin/bash" in script
    assert "tool_bin_suffix='Library/Yoke Bin'" in script
    assert result.evidence["path_state"] == {
        "launcher": f"{xdg_bin_home}/yoke",
        "launcher_present": False,
        "tool_bin_dir": xdg_bin_home,
        "login_path_present": False,
        "ssh_path_present": False,
    }


def test_remote_program_uses_no_clt_interpreter_and_preserves_evidence_opaquely() -> (
    None
):
    syntax = run_zsh_syntax_if_available(FULL_RESET_SCRIPT)
    if syntax is not None:
        assert syntax.returncode == 0, syntax.stderr
    assert FULL_RESET_SCRIPT.startswith("#!/bin/zsh\n")
    assert "python" not in FULL_RESET_SCRIPT.casefold()
    assert "/usr/bin/env" not in FULL_RESET_SCRIPT
    assert EVIDENCE_SOURCE_PATH in FULL_RESET_SCRIPT
    assert RETAINED_EVIDENCE_DIRECTORY in FULL_RESET_SCRIPT
    preserve = FULL_RESET_SCRIPT.index(
        'preserve_evidence\n  remove_directory_target "$home/.yoke"'
    )
    assert preserve > 0
    assert '/bin/mv "$evidence_source"' in FULL_RESET_SCRIPT
    assert '/usr/bin/mktemp -d "$retained_evidence_root/reset.XXXXXX"' in (
        FULL_RESET_SCRIPT
    )
    assert "umask 077\n" in FULL_RESET_SCRIPT
    assert '/bin/cp "$source" "$temporary"' in FULL_RESET_SCRIPT
    assert '/bin/chmod 600 "$target"' in FULL_RESET_SCRIPT
    assert '[[ ! -d "$target" || -L "$target" ]]' in FULL_RESET_SCRIPT
