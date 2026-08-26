"""Filesystem behavior coverage for the uploaded Test Mac zsh program."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
import shlex
import subprocess

from runtime.api.domain.ssh_mac_full_reset_test_support import zsh_binary
from yoke_cli.config import path_doctor
from yoke_core.domain.ssh_mac_full_reset_contract import (
    GOLDEN_MANIFEST_SUFFIX,
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
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


def _isolated_shell_env(
    shell_home: Path, env: dict[str, str] | None = None
) -> dict[str, str]:
    shell_home.mkdir(parents=True, exist_ok=True)
    for startup_file in (".zshenv", ".zprofile", ".zshrc", ".zlogin"):
        (shell_home / startup_file).touch(exist_ok=True)
    return {
        **(env or os.environ),
        "HOME": str(shell_home),
        "ZDOTDIR": str(shell_home),
    }


def _run_functions(
    lines: tuple[str, ...],
    *,
    shell_home: Path,
    env: dict[str, str] | None = None,
    **kwargs,
) -> subprocess.CompletedProcess:
    binary = zsh_binary()
    assert binary is not None
    return subprocess.run(
        [binary, "-f"],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=False,
        env=_isolated_shell_env(shell_home, env),
        **kwargs,
    )


def _require_zsh() -> str:
    binary = zsh_binary()
    if binary is None:
        pytest.skip("zsh is required to execute the macOS reset program")
    return binary


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _baseline_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Build one captured baseline and one contaminated live home beside it."""
    golden = tmp_path / "golden-home"
    home = tmp_path / "live-home"
    _write(golden / ".ssh" / "authorized_keys", "captured-key\n")
    _write(
        golden / "Library" / "Application Support" / "com.apple.TCC" / "TCC.db",
        "captured-privacy-database\n",
    )
    _write(golden / "Library" / "Application Support" / "Vendor" / "auth.json", "{}\n")
    _write(golden / "Library" / "Preferences" / "vendor.plist", "plist\n")
    _write(golden / "Documents" / "notes.txt", "user notes\n")
    _write(golden / ".claude.json", '{"loggedIn": true}\n')
    (tmp_path / ("golden-home" + GOLDEN_MANIFEST_SUFFIX)).write_text("manifest\n")

    _write(home / ".ssh" / "authorized_keys", "live-key\n")
    _write(
        home / "Library" / "Application Support" / "com.apple.TCC" / "TCC.db",
        "live-privacy-database\n",
    )
    _write(home / ".yoke" / "state.json", "{}\n")
    _write(home / "Library" / "Application Support" / "uv" / "cache", "uv\n")
    _write(home / "Documents" / "contaminant.txt", "remove me\n")
    return golden, home


def _clear_and_restore(golden: Path, home: Path, error_log: Path) -> tuple[str, ...]:
    return (
        _function_program(),
        _assignment("home", str(home)),
        _assignment("golden", str(golden)),
        _assignment("restore_error_log", str(error_log)),
        "clear_home_levels",
        "restore_golden_levels",
    )


def test_zsh_program_closes_home_validation_failure_to_a_phase_marker(
    tmp_path: Path,
) -> None:
    binary = _require_zsh()
    result = subprocess.run(
        [binary, "-c", FULL_RESET_SCRIPT, "yoke-reset", "/tmp/not-a-test-home", "/tmp"],
        text=True,
        capture_output=True,
        check=False,
        env=_isolated_shell_env(tmp_path / "shell-home"),
    )
    assert result.returncode == 1
    assert result.stdout.strip() == (
        RESET_FAILURE_PREFIX + RESET_PHASES["validate_home"]
    )


def test_clear_and_restore_keep_the_live_privacy_database_and_ssh_key(
    tmp_path: Path,
) -> None:
    _require_zsh()
    golden, home = _baseline_pair(tmp_path)
    error_log = tmp_path / "restore-errors.log"

    result = _run_functions(
        _clear_and_restore(golden, home, error_log),
        shell_home=tmp_path / "shell-home",
    )

    assert result.returncode == 0, result.stderr
    # Both preserved paths are the LIVE copies, not the captured ones: the
    # privacy database because only a person can re-grant it, and the SSH key
    # because it carries the very command performing the restore.
    live_tcc = home / "Library" / "Application Support" / "com.apple.TCC" / "TCC.db"
    assert live_tcc.read_text() == "live-privacy-database\n"
    assert (home / ".ssh" / "authorized_keys").read_text() == "live-key\n"
    # Everything the baseline holds came back.
    assert (home / ".claude.json").read_text() == '{"loggedIn": true}\n'
    assert (home / "Documents" / "notes.txt").read_text() == "user notes\n"
    assert (home / "Library" / "Application Support" / "Vendor" / "auth.json").exists()
    assert (home / "Library" / "Preferences" / "vendor.plist").exists()
    # Contamination is gone at every depth, including inside a preserved
    # path's own ancestor directory.
    assert not (home / ".yoke").exists()
    assert not (home / "Library" / "Application Support" / "uv").exists()
    assert not (home / "Documents" / "contaminant.txt").exists()
    assert error_log.read_text() == ""


def test_restore_refuses_when_any_entry_could_not_be_copied(
    tmp_path: Path,
) -> None:
    _require_zsh()
    golden, home = _baseline_pair(tmp_path)
    error_log = tmp_path / "restore-errors.log"
    lines = (
        _function_program(),
        _assignment("home", str(home)),
        _assignment("golden", str(golden)),
        _assignment("restore_error_log", str(error_log)),
        "clear_home_levels",
        # A read-only level is the local stand-in for the privacy-protected
        # subtrees a restore without Full Disk Access silently skips.
        f"/bin/chmod 500 {shlex.quote(str(home / 'Library' / 'Application Support'))}",
        "restore_golden || print -r -- RESTORE_REFUSED",
        f"/bin/chmod 700 {shlex.quote(str(home / 'Library' / 'Application Support'))}",
    )

    result = _run_functions(lines, shell_home=tmp_path / "shell-home")

    assert "RESTORE_REFUSED" in result.stdout, result.stdout + result.stderr
    assert error_log.read_text() != ""


def test_full_disk_access_probe_uses_readability_as_the_grant_signal(
    tmp_path: Path,
) -> None:
    _require_zsh()
    readable_probe = _write(tmp_path / "fake-tcc.db", "unit-test probe\n")
    granted = _run_functions(
        (
            _function_program(),
            _assignment("full_disk_access_probe", str(readable_probe)),
            "assert_full_disk_access || print -r -- FDA_DENIED",
        ),
        shell_home=tmp_path / "shell-home",
    )
    denied = _run_functions(
        (
            _function_program(),
            _assignment("full_disk_access_probe", str(tmp_path / "absent-database")),
            "assert_full_disk_access || print -r -- FDA_DENIED",
        ),
        shell_home=tmp_path / "shell-home",
    )
    assert "FDA_DENIED" in denied.stdout
    assert granted.returncode == 0
    assert "FDA_DENIED" not in granted.stdout


def test_validate_golden_refuses_a_baseline_the_clear_would_destroy(
    tmp_path: Path,
) -> None:
    _require_zsh()
    _golden, home = _baseline_pair(tmp_path)
    inside = home / "captured"
    inside.mkdir(parents=True)
    (home / ("captured" + GOLDEN_MANIFEST_SUFFIX)).write_text("manifest\n")
    _write(inside / "keep", "x\n")

    result = _run_functions(
        (
            _function_program(),
            _assignment("home", str(home)),
            _assignment("golden", str(inside)),
            _assignment("manifest_suffix", GOLDEN_MANIFEST_SUFFIX),
            "validate_golden || print -r -- GOLDEN_REFUSED",
        ),
        shell_home=tmp_path / "shell-home",
    )

    assert "GOLDEN_REFUSED" in result.stdout, result.stdout + result.stderr


def test_verify_reports_surviving_yoke_state_after_a_restore(
    tmp_path: Path,
) -> None:
    binary = _require_zsh()
    golden, home = _baseline_pair(tmp_path)
    error_log = tmp_path / "restore-errors.log"
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": str(home), "SHELL": binary}
    )
    verify_lines = (
        _assignment("tool_bin_suffix", "definitely-absent-bin"),
        _assignment("shell_path", binary),
        _assignment("clean_shell_path", "/usr/bin:/bin:/usr/sbin:/sbin"),
        _assignment("tool_bin_dir", str(Path(path_state.tool_bin_dir))),
        "tools=(definitely-no-yoke-reset-tool)",
        "preserved_entries=(.ssh 'Library/Application Support/com.apple.TCC')",
        "yoke_absent_directories=(.yoke)",
        "yoke_absent_files=()",
        "yoke_absent_temp_files=()",
    )

    clean = _run_functions(
        (
            *_clear_and_restore(golden, home, error_log),
            *verify_lines,
            "verify_restored_home || print -r -- VERIFY_FAILED",
        ),
        shell_home=tmp_path / "shell-home",
    )
    assert "VERIFY_FAILED" not in clean.stdout, clean.stdout + clean.stderr

    (home / ".yoke").mkdir()
    contaminated = _run_functions(
        (
            _function_program(),
            _assignment("home", str(home)),
            _assignment("golden", str(golden)),
            *verify_lines,
            "verify_restored_home || print -r -- VERIFY_FAILED",
        ),
        shell_home=tmp_path / "shell-home",
    )
    assert "VERIFY_FAILED" in contaminated.stdout


def test_zsh_program_verifies_shells_without_inheriting_dirty_path(
    tmp_path: Path,
) -> None:
    binary = _require_zsh()
    home = tmp_path / "test-home"
    home.mkdir()
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": str(home), "SHELL": binary}
    )
    tool_bin = Path(path_state.tool_bin_dir)
    dirty_env = {**os.environ, "PATH": f"{tool_bin}:{os.environ.get('PATH', '')}"}
    lines = (
        _function_program(),
        _assignment("shell_path", binary),
        _assignment("clean_shell_path", "/usr/bin:/bin:/usr/sbin:/sbin"),
        _assignment("tool_bin_dir", str(tool_bin)),
        "tools=(definitely-no-yoke-reset-tool)",
        "shell_surface_is_clean -c || print -r -- SURFACE_DIRTY",
        "shell_surface_is_clean -lic || print -r -- SURFACE_DIRTY",
    )

    result = _run_functions(
        lines,
        shell_home=tmp_path / "shell-home",
        env=dirty_env,
    )

    assert "SURFACE_DIRTY" not in result.stdout, result.stdout + result.stderr


def test_shell_surface_check_reports_a_resolvable_tool(tmp_path: Path) -> None:
    binary = _require_zsh()
    tool_bin = tmp_path / "bin"
    tool_bin.mkdir()
    planted = tool_bin / "yoke-reset-probe"
    planted.write_text("#!/bin/sh\nexit 0\n")
    planted.chmod(0o755)
    dirty_env = {**os.environ, "PATH": f"{tool_bin}:{os.environ.get('PATH', '')}"}
    shell_home = tmp_path / "shell-home"
    _write(shell_home / ".zprofile", f"export PATH={tool_bin}:$PATH\n")
    lines = (
        _function_program(),
        _assignment("shell_path", binary),
        _assignment("clean_shell_path", "/usr/bin:/bin"),
        _assignment("tool_bin_dir", str(tool_bin)),
        "tools=(yoke-reset-probe)",
        "shell_surface_is_clean -lic || print -r -- SURFACE_DIRTY",
    )

    result = _run_functions(lines, shell_home=shell_home, env=dirty_env)

    # The earlier program swallowed this failure inside an unchecked loop, so a
    # dirty surface has to be observable on its own before it can gate anything.
    assert "SURFACE_DIRTY" in result.stdout, result.stdout + result.stderr
