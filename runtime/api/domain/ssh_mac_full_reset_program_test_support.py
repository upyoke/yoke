# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

import shlex

import subprocess

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment as _assignment,
    function_program as _function_program,
    isolated_shell_env as _isolated_shell_env,
    require_zsh as _require_zsh,
    run_functions as _run_functions,
)

from yoke_cli.config import path_doctor

from yoke_harness.ssh_mac_full_reset_contract import (
    GOLDEN_MANIFEST_SUFFIX,
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
    RESET_RESTORE_UNRESTORED_PREFIX,
)

from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


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


def _restore_scratch(error_log: Path) -> tuple[str, ...]:
    """Assign and truncate both restore reports, as ``restore_golden`` does."""
    return (
        _assignment("restore_error_log", str(error_log)),
        _assignment("restore_failure_report", str(error_log) + ".entries"),
        "container_runtime_paths=()",
        ': > "$restore_error_log"',
        ': > "$restore_failure_report"',
    )


def _clear_and_restore(golden: Path, home: Path, error_log: Path) -> tuple[str, ...]:
    return (
        _function_program(),
        _assignment("home", str(home)),
        _assignment("golden", str(golden)),
        *_restore_scratch(error_log),
        "clear_home_levels",
        "restore_golden_levels",
    )
