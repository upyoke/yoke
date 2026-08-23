"""Filesystem behavior coverage for the uploaded Test Mac zsh program."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
import shlex
import stat
import subprocess

from runtime.api.domain.ssh_mac_full_reset_test_support import zsh_binary
from yoke_cli.config import path_doctor
from yoke_harness.ssh_mac_full_reset_contract import (
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
)
from yoke_core.domain.ssh_mac_full_reset_contract import (
    EVIDENCE_SOURCE_PATH,
    RESET_RELATIVE_DIRECTORIES,
    RESET_RELATIVE_FILES,
    RETAINED_EVIDENCE_DIRECTORY,
    STARTUP_FILE_NAMES,
    TOKEN_BACKUP_DIRECTORY,
)
from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


def _function_program() -> str:
    functions, separator, _main = FULL_RESET_SCRIPT.partition(
        '\nreset_step="$reset_phase_validate_home"\n'
    )
    assert separator
    return functions


def _assignment(name: str, value: str) -> str:
    return f"{name}={shlex.quote(value)}"


def test_zsh_program_closes_home_validation_failure_to_a_phase_marker() -> None:
    binary = zsh_binary()
    if binary is None:
        pytest.skip("zsh is required to execute the macOS reset program")

    result = subprocess.run(
        [binary, "-c", FULL_RESET_SCRIPT, "yoke-reset", "/tmp/not-a-test-home"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout.strip() == (
        RESET_FAILURE_PREFIX + RESET_PHASES["validate_home"]
    )


def test_zsh_program_verifies_shells_without_inheriting_dirty_path(
    tmp_path: Path,
) -> None:
    binary = zsh_binary()
    if binary is None:
        pytest.skip("zsh is required to execute the macOS reset program")
    home = tmp_path / "test-home"
    home.mkdir()
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": str(home), "SHELL": binary}
    )
    tool_bin = Path(path_state.tool_bin_dir)
    dirty_env = {
        **os.environ,
        "PATH": f"{tool_bin}:{os.environ.get('PATH', '')}",
    }
    lines = (
        _function_program(),
        _assignment("home", str(home)),
        _assignment("shell_path", binary),
        _assignment("clean_shell_path", "/usr/bin:/bin:/usr/sbin:/sbin"),
        _assignment("tool_bin_dir", str(tool_bin)),
        "tools=(definitely-no-yoke-reset-tool)",
        "tool_file_suffixes=(.local/bin/yoke .local/bin/uv .local/bin/uvx)",
        "verify_shell_resolution",
    )

    result = subprocess.run(
        [binary],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
        env=dirty_env,
    )

    assert result.returncode == 0, result.stderr


def test_zsh_program_routes_step_failure_through_closed_phase_marker(
    tmp_path: Path,
) -> None:
    binary = zsh_binary()
    if binary is None:
        pytest.skip("zsh is required to execute the macOS reset program")
    home = tmp_path / "test-home"
    home.mkdir()
    scratch = home / "scratch"
    lines = (
        _function_program(),
        _assignment("home", str(home)),
        _assignment("reset_failure_prefix", RESET_FAILURE_PREFIX),
        _assignment("reset_recovery_failure_marker", "YOKE_RESET_RECOVERY_FAILED"),
        _assignment(
            "reset_phase_verify_shell_resolution",
            RESET_PHASES["verify_shell_resolution"],
        ),
        _assignment("reset_phase_recovery", RESET_PHASES["recovery"]),
        _assignment("stage_backup_temporary", str(scratch / "stage-backup")),
        _assignment("prod_backup_temporary", str(scratch / "prod-backup")),
        _assignment("stage_restore_temporary", str(scratch / "stage-restore")),
        _assignment("prod_restore_temporary", str(scratch / "prod-restore")),
        "startup_file_suffixes=()",
        "tokens_restored=1",
        'reset_step="$reset_phase_verify_shell_resolution"',
        "trap finish EXIT",
        'run_reset_step "$reset_phase_verify_shell_resolution" false',
    )

    result = subprocess.run(
        [binary],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout.strip() == (
        RESET_FAILURE_PREFIX + RESET_PHASES["verify_shell_resolution"]
    )


def test_zsh_program_reaps_ignorant_survivor_through_kill_escalation(
    tmp_path: Path,
) -> None:
    binary = zsh_binary()
    if binary is None:
        pytest.skip("zsh is required to execute the macOS reset program")
    home = tmp_path / "test-home"
    home.mkdir()
    probe_status = tmp_path / "victim.pid"
    marker = "YOKE_REAP_ISOLATION_MARKER.exit"
    lines = (
        _function_program(),
        _assignment("home", str(home)),
        "reap_user=$(/usr/bin/id -un)",
        f"reap_marker_anchor={shlex.quote('YOKE_REAP_ISOLATION_MARKER')}",
        f"reap_marker_suffix={shlex.quote('.exit')}",
        f"reap_onboard_anchor={shlex.quote('yoke-qa-reaper-isolation-onboard')}",
        "reap_target_count=0",
        "reap_failed_count=0",
        "reap_match_count=0",
        'load_average_1min=""',
        "cpu_count=0",
        'reap_failure_detail=""',
        "/bin/sh -c "
        + shlex.quote(
            f'trap "" TERM; : {marker}; printf "%s\\n" "$$" > "$1"; '
            "while :; do /bin/sleep 1; done"
        )
        + " yoke-qa-reaper "
        + shlex.quote(str(probe_status))
        + " >/dev/null 2>&1 &",
        "/bin/sleep 1",
        "victim=$(cat " + shlex.quote(str(probe_status)) + ")",
        "reap_processes",
        "count_reap_matches",
        "record_load_average",
        "if /bin/kill -0 \"$victim\" 2>/dev/null; then",
        "  print -r -- victim-alive:yes",
        "else",
        "  print -r -- victim-alive:no",
        "fi",
        "print -r -- matches:$reap_match_count",
        "print -r -- failed:$reap_failed_count",
    )

    result = subprocess.run(
        [binary],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "victim-alive:no" in result.stdout
    assert "matches:0" in result.stdout
    assert "failed:0" in result.stdout


def test_zsh_program_opaquely_moves_evidence_and_restores_token_bytes(
    tmp_path: Path,
) -> None:
    binary = zsh_binary()
    if binary is None:
        pytest.skip("zsh is required to execute the macOS reset program")
    home = tmp_path / "test-home"
    home.mkdir()
    evidence = home / EVIDENCE_SOURCE_PATH / "campaign" / "report.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("retained-evidence", encoding="utf-8")
    yoke_config = home / ".yoke/config.json"
    yoke_config.write_text("remove", encoding="utf-8")
    ssh_file = home / ".ssh/authorized_keys"
    ssh_file.parent.mkdir()
    ssh_file.write_text("keep", encoding="utf-8")
    for suffix in RESET_RELATIVE_DIRECTORIES:
        target = home / suffix
        target.mkdir(parents=True)
        (target / "state").write_text("remove", encoding="utf-8")
    for suffix in RESET_RELATIVE_FILES:
        target = home / suffix
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("remove", encoding="utf-8")
    (home / "code/checkout/.git").mkdir(parents=True)
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": str(home), "SHELL": "/bin/zsh"}
    )
    tool_bin_suffix = Path(path_state.tool_bin_dir).relative_to(home)
    tool_bin_reference = f"$HOME/{tool_bin_suffix}"
    startup = home / STARTUP_FILE_NAMES[0]
    startup.write_text(
        "keep-before\n"
        f"{path_state.managed_begin}\nremove-managed\n"
        f"{path_state.managed_end}\n"
        "# uv was installed by uv\n"
        f'. "{tool_bin_reference}/env"\n'
        f'source "{tool_bin_reference}/env"\n'
        f'export PATH="{tool_bin_reference}:$PATH"\n'
        "keep-after\n",
        encoding="utf-8",
    )
    stage = tmp_path / "yoke-stage.token"
    prod = tmp_path / "yoke-prod.token"
    stage_bytes = b"stage-secret-byte-sequence"
    prod_bytes = b"prod-secret-byte-sequence"
    stage.write_bytes(stage_bytes)
    prod.write_bytes(prod_bytes)
    install_temp = tmp_path / "yoke-install"
    install_temp.write_text("remove", encoding="utf-8")
    backup = home / TOKEN_BACKUP_DIRECTORY
    lines = (
        _function_program(),
        _assignment("home", str(home)),
        _assignment("tool_bin_dir", path_state.tool_bin_dir),
        f"reset_temp_files=({shlex.quote(str(install_temp))})",
        _assignment("stage_source", str(stage)),
        _assignment("prod_source", str(prod)),
        _assignment("token_backup_directory", str(backup)),
        _assignment("stage_backup", str(backup / "yoke-stage.token")),
        _assignment("prod_backup", str(backup / "yoke-prod.token")),
        _assignment("stage_backup_temporary", str(backup / ".stage.reset-tmp")),
        _assignment("prod_backup_temporary", str(backup / ".prod.reset-tmp")),
        _assignment("stage_restore_temporary", str(tmp_path / ".stage.restore-tmp")),
        _assignment("prod_restore_temporary", str(tmp_path / ".prod.restore-tmp")),
        _assignment("evidence_source", str(home / EVIDENCE_SOURCE_PATH)),
        _assignment(
            "retained_evidence_root",
            str(home / RETAINED_EVIDENCE_DIRECTORY),
        ),
        "stage_saved=0",
        "prod_saved=0",
        'evidence_outcome="ABSENT"',
        'evidence_container=""',
        "preserve_tokens",
        "remove_registered_state",
        "clean_startup_files",
        "restore_tokens",
        "cleanup_scratch",
    )

    result = subprocess.run(
        [binary],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (home / ".yoke").exists()
    moved = tuple(
        (home / RETAINED_EVIDENCE_DIRECTORY).glob(
            "reset.*/installer-smoke-evidence/campaign/report.json"
        )
    )
    assert len(moved) == 1
    assert moved[0].read_text(encoding="utf-8") == "retained-evidence"
    assert ssh_file.read_text(encoding="utf-8") == "keep"
    assert all(not (home / suffix).exists() for suffix in RESET_RELATIVE_DIRECTORIES)
    assert all(not (home / suffix).exists() for suffix in RESET_RELATIVE_FILES)
    assert not install_temp.exists()
    assert list((home / "code").iterdir()) == []
    assert startup.read_text(encoding="utf-8") == "keep-before\nkeep-after\n"
    assert stage.read_bytes() == stage_bytes
    assert prod.read_bytes() == prod_bytes
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert (backup / "yoke-stage.token").read_bytes() == stage_bytes
    assert stat.S_IMODE((backup / "yoke-stage.token").stat().st_mode) == 0o600
