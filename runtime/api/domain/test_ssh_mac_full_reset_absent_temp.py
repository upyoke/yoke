"""Absence-roster coverage for installer temp residue on the Test Mac reset."""

from __future__ import annotations

from pathlib import Path
import shlex

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment as _assignment,
    function_program as _function_program,
    require_zsh as _require_zsh,
    run_functions as _run_functions,
)
from runtime.api.domain.test_ssh_mac_full_reset_program import (
    _baseline_pair,
    _clear_and_restore,
)
from yoke_cli.config import path_doctor
from yoke_harness.ssh_mac_full_reset_contract import (
    INSTALLER_TEMP_PATH,
    RESET_ABSENT_KIND_LEFTOVER,
    RESET_ABSENT_KIND_LIVE_PROCESS,
    RESET_ABSENT_PATH_PREFIX,
    RESET_ABSENT_RECOVERY,
)
from yoke_harness.ssh_mac_full_reset_receipt import absent_path_detail


def _temp_roster(path: Path) -> str:
    return f"yoke_absent_temp_files=({shlex.quote(str(path))})"


def _verify_bindings(home: Path, binary: str) -> tuple[str, ...]:
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": str(home), "SHELL": binary}
    )
    return (
        _assignment("tool_bin_suffix", "definitely-absent-bin"),
        _assignment("shell_path", binary),
        _assignment("clean_shell_path", "/usr/bin:/bin:/usr/sbin:/sbin"),
        _assignment("tool_bin_dir", str(Path(path_state.tool_bin_dir))),
        "tools=(definitely-no-yoke-reset-tool)",
        "preserved_entries=(.ssh 'Library/Application Support/com.apple.TCC')",
        "yoke_absent_directories=(.yoke)",
        "yoke_absent_files=()",
        "container_runtime_paths=()",
        # No test reads the operator's own launchd domain: an unreachable
        # launchctl is how this host reports that nothing is loaded, the same
        # way an absent container runtime reports an idle self-host stack.
        _assignment("launchctl_path", str(home.parent / "absent-launchctl")),
    )


def test_clear_removes_stale_temp_and_golden_restore_still_verifies(
    tmp_path: Path,
) -> None:
    binary = _require_zsh()
    golden, home = _baseline_pair(tmp_path)
    residue = tmp_path / "yoke-install"
    residue.write_text("stale installer\n")
    error_log = tmp_path / "restore-errors.log"

    result = _run_functions(
        (
            *_clear_and_restore(golden, home, error_log),
            _temp_roster(residue),
            *_verify_bindings(home, binary),
            "clear_absent_temp_files || print -r -- CLEAR_FAILED",
            "verify_restored_home || print -r -- VERIFY_FAILED",
        ),
        shell_home=tmp_path / "shell-home",
    )

    assert "CLEAR_FAILED" not in result.stdout, result.stdout + result.stderr
    assert "VERIFY_FAILED" not in result.stdout, result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
    assert not residue.exists()


def test_verify_names_the_exact_unmet_temp_path(
    tmp_path: Path,
) -> None:
    binary = _require_zsh()
    golden, home = _baseline_pair(tmp_path)
    residue = tmp_path / "yoke-install"
    residue.write_text("stale installer\n")
    error_log = tmp_path / "restore-errors.log"
    expected = RESET_ABSENT_PATH_PREFIX + RESET_ABSENT_KIND_LEFTOVER + f" {residue}"

    result = _run_functions(
        (
            *_clear_and_restore(golden, home, error_log),
            _temp_roster(residue),
            *_verify_bindings(home, binary),
            'failure_detail=""',
            'verify_restored_home || print -r -- "VERIFY_FAILED $failure_detail"',
        ),
        shell_home=tmp_path / "shell-home",
    )

    assert "VERIFY_FAILED" in result.stdout, result.stdout + result.stderr
    assert expected in result.stdout
    assert residue.exists()


def test_clear_refuses_while_a_live_process_holds_the_temp_file(
    tmp_path: Path,
) -> None:
    _require_zsh()
    residue = tmp_path / "yoke-install"
    residue.write_text("held installer\n")
    quoted = shlex.quote(str(residue))
    expected = RESET_ABSENT_PATH_PREFIX + RESET_ABSENT_KIND_LIVE_PROCESS + f" {residue}"

    result = _run_functions(
        (
            _function_program(),
            _temp_roster(residue),
            f"/usr/bin/tail -f -- {quoted} >/dev/null 2>&1 &",
            "holder=$!",
            "/bin/sleep 0.3",
            'if ! /bin/kill -0 "$holder" 2>/dev/null; then',
            "  print -r -- HOLDER_DIED",
            "  exit 1",
            "fi",
            'clear_absent_temp_files || print -r -- "LIVE_REFUSED $failure_detail"',
            '/bin/kill "$holder" 2>/dev/null || true',
            'wait "$holder" 2>/dev/null || true',
        ),
        shell_home=tmp_path / "shell-home",
    )

    assert "HOLDER_DIED" not in result.stdout, result.stdout + result.stderr
    assert "LIVE_REFUSED" in result.stdout, result.stdout + result.stderr
    assert expected in result.stdout
    assert residue.exists()


def test_absent_path_detail_names_path_reason_and_recovery() -> None:
    leftover = (
        RESET_ABSENT_PATH_PREFIX
        + RESET_ABSENT_KIND_LEFTOVER
        + " "
        + INSTALLER_TEMP_PATH
    )
    live = (
        RESET_ABSENT_PATH_PREFIX
        + RESET_ABSENT_KIND_LIVE_PROCESS
        + " "
        + INSTALLER_TEMP_PATH
    )
    assert absent_path_detail(leftover) == {
        "path": INSTALLER_TEMP_PATH,
        "reason": RESET_ABSENT_KIND_LEFTOVER,
        "recovery": RESET_ABSENT_RECOVERY[RESET_ABSENT_KIND_LEFTOVER].format(
            path=INSTALLER_TEMP_PATH
        ),
    }
    assert absent_path_detail(live) == {
        "path": INSTALLER_TEMP_PATH,
        "reason": RESET_ABSENT_KIND_LIVE_PROCESS,
        "recovery": RESET_ABSENT_RECOVERY[RESET_ABSENT_KIND_LIVE_PROCESS].format(
            path=INSTALLER_TEMP_PATH
        ),
    }
    assert absent_path_detail(RESET_ABSENT_PATH_PREFIX + "leftover relative") is None
    assert absent_path_detail(
        RESET_ABSENT_PATH_PREFIX + "mystery /tmp/yoke-install"
    ) is (None)
    assert absent_path_detail(RESET_ABSENT_PATH_PREFIX + "leftover /tmp/../etc") is None
