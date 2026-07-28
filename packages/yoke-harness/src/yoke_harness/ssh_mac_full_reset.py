"""Upload, execute, and verify the dedicated Test Mac full reset."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
import shlex
from typing import Protocol

from yoke_cli.config.path_doctor import (
    PathStateContract,
    resolve_path_state_contract,
)

from yoke_harness.ssh_mac_full_reset_contract import (
    EVIDENCE_SOURCE_PATH,
    FULL_RESET_MARKER,
    FULL_RESET_REMOTE_PATH,
    FullResetPathContract,
    HOMEBREW_PATH,
    RESET_RELATIVE_DIRECTORIES,
    RESET_TEMP_FILES,
    RETAINED_EVIDENCE_DIRECTORY,
    TOKEN_BACKUP_DIRECTORY,
    TOKEN_LOCATIONS,
    resolve_full_reset_path_contract,
)
from yoke_harness.ssh_mac_full_reset_script import render_full_reset_script
from yoke_harness.test_machine_types import HostActionResult


class ResetCommandResult(Protocol):
    returncode: int
    stdout: str


class ResetRunner(Protocol):
    def __call__(
        self,
        command: str,
        *,
        timeout: int = 60,
    ) -> ResetCommandResult: ...


class ResetUploader(Protocol):
    def __call__(self, path: str, content: str) -> None: ...


def is_safe_test_mac_home(home: str) -> bool:
    """Accept only one explicit, normalized macOS user home."""
    selected = PurePosixPath(home)
    if (
        home in {"", "/", "~", "$HOME"}
        or "~" in home
        or "$" in home
        or home != str(selected)
        or selected.parts[:2] != ("/", "Users")
        or len(selected.parts) != 3
    ):
        return False
    user = selected.name
    return (
        user.casefold() != "shared"
        and user not in {".", ".."}
        and re.fullmatch(r"[A-Za-z0-9._-]+", user) is not None
    )


def _command(*argv: str) -> str:
    return shlex.join(argv)


def _closed_outcomes(stdout: str) -> dict[str, str] | None:
    lines = tuple(line.strip() for line in stdout.splitlines() if line.strip())
    token_outcomes: dict[str, str] = {}
    evidence_outcome: str | None = None
    expected_prefixes = {
        f"YOKE_TOKEN_{label}_": label for _source, _backup, label in TOKEN_LOCATIONS
    }
    for line in lines:
        if line == FULL_RESET_MARKER:
            continue
        if line in {
            "YOKE_INSTALLER_EVIDENCE_MOVED",
            "YOKE_INSTALLER_EVIDENCE_RETAINED",
            "YOKE_INSTALLER_EVIDENCE_ABSENT",
        }:
            evidence_outcome = line.removeprefix("YOKE_INSTALLER_EVIDENCE_").lower()
            continue
        matched = False
        for prefix, label in expected_prefixes.items():
            if line in {prefix + "RESTORED", prefix + "ABSENT"}:
                token_outcomes[label] = line.removeprefix(prefix).lower()
                matched = True
                break
        if not matched:
            return None
    if (
        len(lines) != 4
        or lines.count(FULL_RESET_MARKER) != 1
        or evidence_outcome is None
        or set(token_outcomes) != set(expected_prefixes.values())
    ):
        return None
    return {**token_outcomes, "evidence": evidence_outcome}


def _success_evidence(
    contract: FullResetPathContract,
    outcomes: dict[str, str],
) -> dict[str, object]:
    home = contract.home
    rows: list[dict[str, str]] = [
        {"path": f"{home}/.yoke", "outcome": "removed"},
        {
            "path": f"{home}/{EVIDENCE_SOURCE_PATH}",
            "outcome": "moved" if outcomes["evidence"] == "moved" else "absent",
        },
        {
            "path": f"{home}/{RETAINED_EVIDENCE_DIRECTORY}",
            "outcome": (
                "preserved"
                if outcomes["evidence"] in {"moved", "retained"}
                else "absent"
            ),
        },
    ]
    rows.extend(
        {"path": f"{home}/{suffix}", "outcome": "removed"}
        for suffix in RESET_RELATIVE_DIRECTORIES
    )
    rows.extend(
        {"path": path, "outcome": "removed"} for path in contract.tool_file_paths
    )
    rows.extend({"path": path, "outcome": "removed"} for path in RESET_TEMP_FILES)
    rows.append(
        {
            "path": f"{home}/{TOKEN_BACKUP_DIRECTORY}",
            "outcome": "mode-0700",
        }
    )
    for source, backup_name, label in TOKEN_LOCATIONS:
        outcome = outcomes[label]
        rows.extend(
            (
                {
                    "path": f"{home}/{TOKEN_BACKUP_DIRECTORY}/{backup_name}",
                    "outcome": (
                        "preserved-mode-0600" if outcome == "restored" else "not-copied"
                    ),
                },
                {
                    "path": source,
                    "outcome": (
                        "restored-mode-0600" if outcome == "restored" else "absent"
                    ),
                },
            )
        )
    rows.extend(
        (
            {"path": f"{home}/code", "outcome": "children-removed"},
            {"path": HOMEBREW_PATH, "outcome": "uv-absent"},
        )
    )
    rows.extend(
        {
            "path": path,
            "outcome": "cleaned-or-absent",
        }
        for path in contract.startup_files
    )
    rows.extend(
        (
            {
                "path": contract.shell_path,
                "outcome": "login-and-ssh-resolution-clean",
            },
            {
                "path": contract.tool_bin_dir,
                "outcome": "absent-from-login-and-ssh-path",
            },
            {"path": FULL_RESET_REMOTE_PATH, "outcome": "removed"},
        )
    )
    return {
        "paths": rows,
        "path_state": {
            "launcher": contract.launcher_path,
            "launcher_present": False,
            "tool_bin_dir": contract.tool_bin_dir,
            "login_path_present": False,
            "ssh_path_present": False,
        },
    }


def execute_full_test_mac_reset(
    *,
    run_remote: ResetRunner,
    upload_text: ResetUploader,
    home: str,
    path_state: PathStateContract | None = None,
) -> HostActionResult:
    """Run the full reset with closed output and deterministic script cleanup."""
    if not is_safe_test_mac_home(home):
        return HostActionResult(
            False,
            {"paths": []},
            "unsafe_test_mac_home",
        )
    selected_path_state = path_state or resolve_path_state_contract(
        env={"HOME": home, "SHELL": "/bin/zsh"}
    )
    if selected_path_state.home != home:
        return HostActionResult(
            False,
            {"paths": []},
            "test_mac_path_home_mismatch",
        )
    try:
        reset_contract = resolve_full_reset_path_contract(selected_path_state)
    except ValueError:
        return HostActionResult(
            False,
            {"paths": []},
            "unsafe_test_mac_tool_path",
        )
    reset_script = render_full_reset_script(reset_contract)

    reset_ok = False
    error_code = "test_mac_reset_failed"
    outcomes: dict[str, str] | None = None
    try:
        preclean = run_remote(
            _command("/bin/rm", "-f", "--", FULL_RESET_REMOTE_PATH),
        )
        if int(preclean.returncode) != 0:
            error_code = "test_mac_reset_script_preclean_failed"
        else:
            upload_text(FULL_RESET_REMOTE_PATH, reset_script)
            mode = run_remote(
                _command("/bin/chmod", "0700", FULL_RESET_REMOTE_PATH),
            )
            if int(mode.returncode) != 0:
                error_code = "test_mac_reset_script_mode_failed"
            else:
                result = run_remote(
                    _command(FULL_RESET_REMOTE_PATH, home),
                    timeout=300,
                )
                if int(result.returncode) == 0:
                    outcomes = _closed_outcomes(str(result.stdout))
                    if outcomes is not None:
                        reset_ok = True
                    else:
                        error_code = "test_mac_reset_output_invalid"
    except Exception:
        error_code = "test_mac_reset_adapter_failed"

    cleanup_ok = False
    try:
        cleanup = run_remote(
            _command("/bin/rm", "-f", "--", FULL_RESET_REMOTE_PATH),
        )
        cleanup_ok = int(cleanup.returncode) == 0
    except Exception:
        cleanup_ok = False
    if not cleanup_ok:
        reset_ok = False
        error_code = "test_mac_reset_script_cleanup_failed"

    if reset_ok and outcomes is not None:
        return HostActionResult(True, _success_evidence(reset_contract, outcomes))
    return HostActionResult(
        False,
        {
            "paths": [
                {"path": home, "outcome": "reset-failed"},
                {
                    "path": FULL_RESET_REMOTE_PATH,
                    "outcome": "removed" if cleanup_ok else "cleanup-failed",
                },
            ]
        },
        error_code,
    )


__all__ = [
    "execute_full_test_mac_reset",
    "is_safe_test_mac_home",
]
