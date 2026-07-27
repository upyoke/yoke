"""Rendered-program contract coverage for dedicated Test Mac reset."""

from __future__ import annotations

import subprocess
from pathlib import Path

from runtime.api.domain.ssh_mac_full_reset_test_support import FakeResetTransport
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
        "\n".join(
            (
                "YOKE_TOKEN_STAGE_ABSENT",
                "YOKE_TOKEN_PROD_ABSENT",
                "YOKE_INSTALLER_EVIDENCE_ABSENT",
                FULL_RESET_MARKER,
            )
        )
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
    syntax = subprocess.run(
        ["/bin/zsh", "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
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
    syntax = subprocess.run(
        ["/bin/zsh", "-n"],
        input=FULL_RESET_SCRIPT,
        text=True,
        capture_output=True,
        check=False,
    )

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
