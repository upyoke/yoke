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
    FULL_RESET_REMOTE_PATH,
    resolve_full_reset_path_contract,
)
from yoke_harness.ssh_mac_full_reset_receipt import (
    closed_outcomes,
    failure_outcome,
    success_evidence,
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
    outcomes: dict[str, str | int | float] | None = None
    parsed_failure: tuple[str, bool, str | None] | None = None
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
                    outcomes = closed_outcomes(str(result.stdout))
                    if outcomes is not None:
                        reset_ok = True
                    else:
                        error_code = "test_mac_reset_output_invalid"
                else:
                    parsed_failure = failure_outcome(str(result.stdout))
                    if parsed_failure is not None:
                        phase, recovery_failed, _reap_detail = parsed_failure
                        error_code = (
                            "test_mac_reset_recovery_failed"
                            if recovery_failed
                            else f"test_mac_reset_{phase}_failed"
                        )
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
        return HostActionResult(True, success_evidence(reset_contract, outcomes))
    failure_evidence: dict[str, object] = {
        "paths": [
            {"path": home, "outcome": "reset-failed"},
            {
                "path": FULL_RESET_REMOTE_PATH,
                "outcome": "removed" if cleanup_ok else "cleanup-failed",
            },
        ]
    }
    if parsed_failure is not None:
        phase, recovery_failed, reap_detail = parsed_failure
        failure_evidence.update(
            {
                "reset_phase": phase,
                "recovery_cleanup": "failed" if recovery_failed else "completed",
            }
        )
        if reap_detail is not None:
            reap_parts = reap_detail.split()
            failure_evidence["process_state"] = {
                "surviving_reap_failures": int(reap_parts[0]),
                "surviving_matches": int(reap_parts[1]),
                "load_average": float(reap_parts[2]),
            }
    return HostActionResult(
        False,
        failure_evidence,
        error_code,
    )


__all__ = [
    "execute_full_test_mac_reset",
    "is_safe_test_mac_home",
]
