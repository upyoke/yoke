"""Filesystem proof of exact OS-managed exclusion and live preservation."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import sys

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment,
    function_program,
    require_zsh,
    run_functions,
)
from yoke_harness.ssh_mac_preserved_state import (
    OS_MANAGED_HOME_ENTRIES,
    OS_MANAGED_MANIFEST_KEY,
    OS_MANAGED_MANIFEST_VALUE,
    render_preserved_state_contract,
)


def _contract(home: Path) -> tuple[str, ...]:
    require_zsh()
    contract = render_preserved_state_contract()
    if sys.platform != "darwin":
        contract = contract.replace("stat -f '%u:%g'", "stat -c '%u:%g'")
    # The scratch fixture's actual owner is the expected owner for execution;
    # production always renders the fixed root:wheel policy.
    return (
        function_program(),
        contract,
        assignment("home", str(home)),
        assignment("os_managed_owner", f"{os.getuid()}:{os.getgid()}"),
        "failure_detail=''",
    )


def _file(home: Path) -> Path:
    target = home / OS_MANAGED_HOME_ENTRIES[0]
    target.parent.mkdir(parents=True)
    target.write_text("live OS state")
    return target


@pytest.mark.parametrize("invalid", ["owner", "directory", "symlink", "ancestor"])
def test_declared_entry_refuses_wrong_owner_type_or_symlink_ancestor(tmp_path, invalid):
    home = tmp_path / "home"
    target = _file(home)
    lines = _contract(home)
    if invalid == "owner":
        lines += (assignment("os_managed_owner", "unexpected-owner"),)
    elif invalid == "directory":
        target.unlink()
        target.mkdir()
    elif invalid == "symlink":
        target.unlink()
        target.symlink_to("absent")
    else:
        target.parent.rename(target.parent.with_name("original"))
        target.parent.symlink_to("original", target_is_directory=True)
    result = run_functions(
        (*lines, "assert_os_managed_preserved_state || print -r -- REJECTED"),
        shell_home=tmp_path / "shell",
    )
    assert "REJECTED" in result.stdout, result.stderr


def test_capture_excludes_only_exact_validated_entry_and_preserves_neighbors(tmp_path):
    home = tmp_path / "home"
    target = _file(home)
    neighbor = target.with_name("neighbor.plist")
    neighbor.write_text("ordinary user state")
    result = run_functions(
        (
            *_contract(home),
            "assert_os_managed_preserved_state",
            f"cd -- {shlex.quote(str(home))}",
            "list_capture_entries",
        ),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    entries = result.stdout.split("\0")
    assert "./" + str(target.relative_to(home)) not in entries
    assert "./" + str(neighbor.relative_to(home)) in entries


def test_foreign_owner_scan_does_not_exempt_neighbor_or_parent_directory(tmp_path):
    home = tmp_path / "home"
    target = _file(home)
    neighbor = target.with_name("foreign.plist")
    neighbor.write_text("must refuse")
    result = run_functions(
        (
            *_contract(home),
            assignment("capture_user", str(os.getuid() + 1)),
            "list_foreign_home_entries",
        ),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    entries = result.stdout.splitlines()
    assert str(target) not in entries
    assert str(neighbor) in entries
    assert str(target.parent) in entries


def test_reset_keeps_live_entry_and_restores_other_container_state(tmp_path):
    home, golden = tmp_path / "home", tmp_path / "golden"
    target = _file(home)
    inode = target.stat().st_ino
    target.chmod(0o600)
    captured_target = _file(golden)
    captured_target.write_text("older OS state must not overwrite live state")
    (captured_target.parent / "vendor.plist").write_text("captured vendor state")
    (target.parent / "contaminant").write_text("remove")
    error = tmp_path / "restore-errors"
    result = run_functions(
        (
            *_contract(home),
            assignment("golden", str(golden)),
            assignment("restore_error_log", str(error)),
            assignment("restore_failure_report", str(error) + ".entries"),
            ': > "$restore_error_log"',
            ': > "$restore_failure_report"',
            "clear_home_levels",
            "restore_golden_levels",
            "assert_os_managed_preserved_state",
        ),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    assert target.read_text() == "live OS state"
    assert target.stat().st_ino == inode
    assert target.stat().st_mode & 0o777 == 0o600
    assert (target.parent / "vendor.plist").read_text() == "captured vendor state"
    assert not (target.parent / "contaminant").exists()
    assert error.read_text() == ""


@pytest.mark.parametrize("manifest", ["legacy", "declared", "mismatch", "copied_entry"])
def test_reset_manifest_accepts_legacy_and_valid_declared_state_only(
    tmp_path, manifest
):
    home, golden = tmp_path / "home", tmp_path / "golden"
    home.mkdir()
    golden.mkdir()
    line = OS_MANAGED_MANIFEST_KEY + " " + OS_MANAGED_MANIFEST_VALUE
    if manifest == "mismatch":
        line = OS_MANAGED_MANIFEST_KEY + " []"
    if manifest == "legacy":
        line = "source_home legacy"
    if manifest == "copied_entry":
        _file(golden)
    Path(str(golden) + ".manifest").write_text(line + "\n")
    result = run_functions(
        (
            *_contract(home),
            assignment("golden", str(golden)),
            "manifest_suffix=.manifest",
            "validate_preserved_manifest || print -r -- REJECTED",
        ),
        shell_home=tmp_path / "shell",
    )
    assert ("REJECTED" in result.stdout) == (manifest in {"mismatch", "copied_entry"})


def test_absent_optional_os_state_does_not_block_validation(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = run_functions(
        (*_contract(home), "assert_os_managed_preserved_state"),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
