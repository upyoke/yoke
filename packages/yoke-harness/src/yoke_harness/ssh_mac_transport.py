"""Client-side SSH transport and host primitives for the dedicated Test Machine."""

from __future__ import annotations

import base64
import shlex
import subprocess
from typing import Any, Mapping, Sequence

from yoke_contracts.machine_qa_execution import (
    GUI_SESSION_CONTEXT,
    REQUIRED_SESSION_CONTEXT_FIELD,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE,
    terminal_bridge_recovery,
)
from yoke_harness.ssh_mac_host_session_state import (
    SCREEN_SAVER_ENABLED_ERROR,
    SCREEN_SAVER_PROBE_ERROR,
    read_console_user,
    read_screen_saver_idle_seconds,
    screen_saver_recovery,
)
from yoke_harness.ssh_mac_baseline_probes import prove_declared_probes
from yoke_harness.ssh_mac_full_reset import execute_full_test_machine_reset
from yoke_harness.ssh_mac_golden_capture import capture_golden_baseline
from yoke_harness.ssh_mac_terminal_bridge_diagnose import (
    diagnose_terminal_app_control,
)
from yoke_harness.ssh_mac_gui_session import (
    classify_macos_session_context_failure,
    run_terminal_app_command,
)
from yoke_harness.ssh_mac_terminal_bridge_check import (
    named_failure,
    verify_terminal_app_control,
)
from yoke_harness.test_machine_types import HostActionResult


from yoke_harness.ssh_test_machine_transport import SSH_OPTIONS, SshTestMachineTransport


class SshMacTransport(SshTestMachineTransport):
    """Bounded SSH operations shared by Test Machine client adapters."""

    def _host_facts(self) -> dict[str, Any]:
        script = (
            'print -r -- "$HOME"; '
            'print -r -- "${SHELL:-/bin/zsh}"; '
            'print -r -- "${XDG_BIN_HOME:-}"'
        )
        result = self._run(
            "/bin/zsh -fc " + shlex.quote(script),
            timeout=20,
        )
        if result.returncode:
            raise HostControlLocalError(
                code="host_control_connection_failed",
                phase="host_facts_ssh",
                detail="SSH could not collect test-machine host facts",
                exit_code=int(result.returncode),
                stderr=result.stderr,
                recovery_hint="Check the SSH host, user, network, and key authorization; retry.",
            )
        values = result.stdout.split("\n")
        if len(values) < 3 or not values[0]:
            raise HostControlLocalError(
                code="host_control_host_facts_malformed",
                phase="host_facts_parse",
                detail=f"SSH returned malformed host facts: {result.stdout}",
                exit_code=int(result.returncode),
                stderr=result.stderr,
                recovery_hint="Repair the remote HOME and SHELL facts, then retry.",
            )
        return {
            "home": values[0],
            "shell": values[1] or "/bin/zsh",
            "xdg_bin_home": values[2] or None,
        }

    @staticmethod
    def _zsh_command(script: str, *args: str) -> str:
        return (
            "/bin/zsh -fc "
            + shlex.quote(script)
            + " yoke-host-control "
            + shlex.join(args)
        )

    def check_connection(self) -> HostActionResult:
        result = self._run("/usr/bin/true", timeout=20)
        return HostActionResult(
            ok=result.returncode == 0,
            error_code=None if result.returncode == 0 else "ssh_unavailable",
            evidence={
                "transport": "ssh",
                "host": self._host,
                "user": self._user,
                "runner_materialized": result.returncode == 0,
            },
        )

    def check_terminal_bridge(self) -> HostActionResult:
        console_user = read_console_user(self._run)
        if console_user != self._user:
            code = TERMINAL_CONSOLE_USER_MISMATCH_ERROR_CODE
            return HostActionResult(
                False,
                {
                    "terminal_backend": "Terminal.app",
                    "console_user": console_user,
                    "expected_console_user": self._user,
                    "recovery": terminal_bridge_recovery(code),
                    "capture_diagnostics": named_failure(
                        code, {"console_user": console_user}
                    ),
                },
                code,
            )
        idle = read_screen_saver_idle_seconds(self._run, console_user)
        saver_evidence = {
            "console_user": console_user,
            "screen_saver_idle_seconds": idle,
        }
        if idle != 0:
            return HostActionResult(
                False,
                {
                    "terminal_backend": "Terminal.app",
                    **saver_evidence,
                    "recovery": screen_saver_recovery(idle),
                },
                SCREEN_SAVER_PROBE_ERROR
                if idle is None
                else SCREEN_SAVER_ENABLED_ERROR,
            )
        ok, evidence, error_code = verify_terminal_app_control(
            self._run,
            expected_console_user=self._user,
        )
        return HostActionResult(
            ok=ok,
            error_code=error_code,
            evidence={"terminal_backend": "Terminal.app", **saver_evidence, **evidence},
        )

    def diagnose_terminal_bridge(self) -> HostActionResult:
        """Run every bridge capability alone and name what blocks each one."""
        return diagnose_terminal_app_control(
            self._run,
            expected_console_user=self._user,
        )

    def capture_golden_baseline(
        self,
        destination: str,
        *,
        probes_document: str | None = None,
    ) -> HostActionResult:
        """Copy this host's home into a new restorable baseline."""
        return capture_golden_baseline(
            self,
            destination=destination,
            probes_document=probes_document,
        )

    def upload_remote_text(self, path: str, content: str) -> None:
        """Write one owner-only text file to the host."""
        result = self._run(
            self._zsh_command('umask 077; /bin/cat > "$1"', path),
            input_text=content,
        )
        if result.returncode:
            raise RuntimeError("host_control file write failed")

    def reset_installer_test_host(self) -> HostActionResult:
        """Restore the declared golden baseline over the dedicated host's home."""
        return execute_full_test_machine_reset(
            run_remote=self._run,
            upload_text=self.upload_remote_text,
            home=self.home,
            golden_baseline_path=self.golden_baseline_path,
            path_state=self.path_state,
        )

    def prove_user_equivalent(self) -> HostActionResult:
        """Run the probes the declared baseline carries beside itself."""
        return prove_declared_probes(self)

    def read_remote_text(self, path: str) -> str | None:
        """Return one regular remote file as text, or None when it is absent."""
        reader = (
            'target="$1"; '
            '[[ "$target" == /* ]] || exit 64; '
            'if [[ -e "$target" ]]; then '
            '[[ -f "$target" && ! -L "$target" ]] || exit 65; '
            '/usr/bin/base64 < "$target"; '
            "fi"
        )
        result = self._run(self._zsh_command(reader, path))
        if result.returncode:
            raise RuntimeError("host_control file read failed")
        encoded = result.stdout.strip()
        return base64.b64decode(encoded).decode("utf-8") if encoded else None

    def _upload_bytes(self, path: str, content: bytes) -> bool:
        writer = (
            'target="$1"; '
            '[[ "$target" == /* ]] || exit 64; '
            'parent="${target:h}"; '
            '/bin/mkdir -p "$parent" || exit 65; '
            'temporary="${target}.yoke-upload.$$"; '
            "trap '/bin/rm -f \"$temporary\"' EXIT HUP INT TERM; "
            "umask 077; "
            '/usr/bin/base64 -D > "$temporary" || exit 66; '
            '/bin/chmod 600 "$temporary" || exit 67; '
            '/bin/mv -f "$temporary" "$target" || exit 68; '
            "trap - EXIT HUP INT TERM"
        )
        result = self._run(
            self._zsh_command(writer, path),
            input_text=base64.b64encode(content).decode("ascii"),
        )
        return result.returncode == 0

    def run_command(
        self,
        argv: Sequence[str],
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        """Run argv through SSH or the GUI session, preserving empty option values."""
        normalized = tuple(str(value) for value in argv)
        if not normalized or not normalized[0]:
            raise ValueError("host_control command requires a non-empty executable")
        if required_session_context == GUI_SESSION_CONTEXT:
            return run_terminal_app_command(
                self._run,
                argv=normalized,
                timeout=timeout,
            )
        if required_session_context is not None:
            raise ValueError(
                f"unknown host_control session context {required_session_context!r}"
            )
        return self._run(shlex.join(normalized), timeout=timeout)

    def run_machine_assertions(
        self,
        assertions: Sequence[Mapping[str, Any]],
    ) -> HostActionResult:
        rows: list[dict[str, Any]] = []
        for assertion in assertions:
            argv = [str(value) for value in assertion["argv"]]
            expected = int(assertion.get("expected_exit", 0))
            required_context = assertion.get(REQUIRED_SESSION_CONTEXT_FIELD)
            result = self.run_command(
                argv,
                required_session_context=(
                    str(required_context) if required_context is not None else None
                ),
            )
            execution_context = required_context or "ssh"
            context_failure = (
                classify_macos_session_context_failure(result)
                if result.returncode != 0
                else None
            )
            row = {
                "argv": argv,
                "expected_exit": expected,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "execution_context": execution_context,
            }
            if required_context is not None:
                row[REQUIRED_SESSION_CONTEXT_FIELD] = required_context
            if context_failure is not None:
                row["session_context_degraded_reason"] = context_failure.reason
            rows.append(row)
            if context_failure is not None or result.returncode != expected:
                evidence: dict[str, Any] = {
                    "assertions": rows,
                    "secret_scan": "pending-redaction",
                }
                if context_failure is not None:
                    evidence["session_context_degraded_reason"] = context_failure.reason
                return HostActionResult(
                    False,
                    evidence,
                    (
                        context_failure.error_code
                        if context_failure is not None
                        else "machine_assertion_failed"
                    ),
                )
        return HostActionResult(
            True,
            {"assertions": rows, "secret_scan": "passed-after-redaction"},
        )


__all__ = ["SSH_OPTIONS", "SshMacTransport"]
