"""Upload, execute, and verify the dedicated Test Machine full reset."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
import shlex
from typing import Protocol

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_cli.config.path_doctor import (
    PathStateContract,
    resolve_path_state_contract,
)

from yoke_harness.ssh_mac_full_reset_contract import (
    FULL_RESET_REMOTE_PATH,
    RESET_ABSENT_PATH_PREFIX,
    RESET_RELAY_SERVICE_PREFIX,
    RESET_RESTORE_UNRESTORED_PREFIX,
    golden_baseline_clears_home,
    resolve_full_reset_path_contract,
)
from yoke_harness.ssh_mac_full_reset_receipt import (
    absent_path_detail,
    closed_outcomes,
    failure_outcome,
    relay_service_detail,
    success_evidence,
    unrestored_detail,
)
from yoke_harness.ssh_mac_full_reset_script import render_full_reset_script
from yoke_harness.ssh_test_machine_transport import TRANSPORT_FAILURE_EXIT
from yoke_harness.test_machine_types import HostActionResult


TEST_MAC_RESET_ADAPTER_FAILED = "test_mac_reset_adapter_failed"
# The runner could not start or finish ssh; the host itself may be fine.
TEST_MAC_RESET_TRANSPORT_FAILED = "test_mac_reset_transport_failed"


class ResetCommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


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


class _ResetCalls:
    """Run reset steps, keep the first error code and evidence per failed call."""

    def __init__(self, run_remote: ResetRunner) -> None:
        self._run_remote = run_remote
        self.error_code: str | None = None
        self.failures: list[dict[str, object]] = []
        self.last_exit_code: int | None = None
        self.last_stdout = ""

    def fail(self, code: str) -> None:
        if self.error_code is None:
            self.error_code = code

    def _raised(self, call: str, error: Exception) -> None:
        self.last_exit_code = None
        self.failures.append(
            {
                "call": call,
                "exception_type": type(error).__name__,
                "exception": bounded_machine_qa_diagnostic(error),
            }
        )
        self.fail(TEST_MAC_RESET_ADAPTER_FAILED)

    def run(
        self,
        call: str,
        command: str,
        failure_code: str | None,
        *,
        timeout: int = 60,
    ) -> ResetCommandResult | None:
        """Return the result when the call exited 0, else record why not."""
        try:
            result = self._run_remote(command, timeout=timeout)
            exit_code = int(result.returncode)
        except Exception as error:
            self._raised(call, error)
            return None
        self.last_exit_code = exit_code
        self.last_stdout = str(result.stdout)
        if exit_code == 0:
            return result
        self.failures.append(
            {
                "call": call,
                "exit_code": exit_code,
                "stderr": bounded_machine_qa_diagnostic(result.stderr),
            }
        )
        if exit_code == TRANSPORT_FAILURE_EXIT:
            self.fail(TEST_MAC_RESET_TRANSPORT_FAILED)
        elif failure_code is not None:
            self.fail(failure_code)
        return None

    def upload(self, upload_text: ResetUploader, path: str, content: str) -> bool:
        try:
            upload_text(path, content)
        except Exception as error:
            self._raised("upload", error)
            return False
        return True


def execute_full_test_machine_reset(
    *,
    run_remote: ResetRunner,
    upload_text: ResetUploader,
    home: str,
    golden_baseline_path: str | None,
    path_state: PathStateContract | None = None,
) -> HostActionResult:
    """Restore the declared golden baseline with closed output and cleanup."""
    if not is_safe_test_mac_home(home):
        return HostActionResult(
            False,
            {"paths": []},
            "unsafe_test_mac_home",
        )
    if not golden_baseline_path:
        return HostActionResult(
            False,
            {"paths": []},
            "test_mac_golden_baseline_not_declared",
        )
    if not golden_baseline_clears_home(golden_baseline_path, home=home):
        return HostActionResult(
            False,
            {"paths": []},
            "test_mac_golden_baseline_unsafe",
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

    calls = _ResetCalls(run_remote)
    outcomes: dict[str, str | int | float] | None = None
    parsed_failure: tuple[str, bool, str | None] | None = None
    preclean = calls.run(
        "preclean",
        _command("/bin/rm", "-f", "--", FULL_RESET_REMOTE_PATH),
        "test_mac_reset_script_preclean_failed",
    )
    if preclean is not None and calls.upload(
        upload_text, FULL_RESET_REMOTE_PATH, reset_script
    ):
        mode = calls.run(
            "mode",
            _command("/bin/chmod", "0700", FULL_RESET_REMOTE_PATH),
            "test_mac_reset_script_mode_failed",
        )
        if mode is not None:
            result = calls.run(
                "reset",
                _command(FULL_RESET_REMOTE_PATH, home, golden_baseline_path),
                None,
                timeout=900,
            )
            if result is not None:
                outcomes = closed_outcomes(str(result.stdout))
                if outcomes is None:
                    calls.fail("test_mac_reset_output_invalid")
            elif calls.last_exit_code not in {None, TRANSPORT_FAILURE_EXIT}:
                parsed_failure = failure_outcome(calls.last_stdout)
                if parsed_failure is None:
                    calls.fail("test_mac_reset_failed")
                else:
                    phase, recovery_failed, _reap_detail = parsed_failure
                    calls.fail(
                        "test_mac_reset_recovery_failed"
                        if recovery_failed
                        else f"test_mac_reset_{phase}_failed"
                    )

    # Cleanup always runs. Its failure is reported, but never replaces the
    # first error: that one names why the reset stopped.
    cleanup_ok = (
        calls.run(
            "cleanup",
            _command("/bin/rm", "-f", "--", FULL_RESET_REMOTE_PATH),
            "test_mac_reset_script_cleanup_failed",
        )
        is not None
    )

    if calls.error_code is None and outcomes is not None:
        return HostActionResult(
            True,
            success_evidence(
                reset_contract,
                outcomes,
                golden_baseline_path=golden_baseline_path,
            ),
        )
    failure_evidence: dict[str, object] = {
        "paths": [
            {"path": home, "outcome": "reset-failed"},
            {"path": golden_baseline_path, "outcome": "not-restored"},
            {
                "path": FULL_RESET_REMOTE_PATH,
                "outcome": "removed" if cleanup_ok else "cleanup-failed",
            },
        ],
        "failed_calls": calls.failures,
    }
    if parsed_failure is not None:
        phase, recovery_failed, detail = parsed_failure
        failure_evidence.update(
            {
                "reset_phase": phase,
                "recovery_cleanup": "failed" if recovery_failed else "completed",
            }
        )
        if detail is not None and detail.startswith(RESET_RESTORE_UNRESTORED_PREFIX):
            # The restore names what it could not return. Without this the
            # receipt carried only the phase, and diagnosis meant repeating the
            # whole restore on the host just to watch where it stopped. Each
            # entry also carries its copier error excerpt, which is the cause.
            failure_evidence["restore_state"] = unrestored_detail(detail)
        elif detail is not None and detail.startswith(RESET_ABSENT_PATH_PREFIX):
            failure_evidence["absent_state"] = absent_path_detail(detail)
        elif detail is not None and detail.startswith(RESET_RELAY_SERVICE_PREFIX):
            # The home is still intact here: the reset stops on a relay it
            # could not unload rather than clearing under a service that would
            # rewrite the home it just emptied.
            failure_evidence["relay_service_state"] = relay_service_detail(detail)
        elif detail is not None:
            reap_parts = detail.split()
            failure_evidence["process_state"] = {
                "surviving_reap_failures": int(reap_parts[0]),
                "surviving_matches": int(reap_parts[1]),
                "load_average": float(reap_parts[2]),
            }
    return HostActionResult(
        False,
        failure_evidence,
        calls.error_code or "test_mac_reset_failed",
    )


__all__ = [
    "TEST_MAC_RESET_ADAPTER_FAILED",
    "TEST_MAC_RESET_TRANSPORT_FAILED",
    "execute_full_test_machine_reset",
    "is_safe_test_mac_home",
]
