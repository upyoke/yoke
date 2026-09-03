"""Client-side SSH transport and host primitives for the dedicated Test Mac."""

from __future__ import annotations

import base64
from pathlib import Path
import shlex
import subprocess
from typing import Any, Mapping, Sequence

from yoke_cli.config.path_doctor import (
    PathStateContract,
    resolve_path_state_contract,
)
from yoke_contracts.machine_qa_execution import (
    GUI_SESSION_CONTEXT,
    REQUIRED_SESSION_CONTEXT_FIELD,
)
from yoke_harness.ssh_mac_baseline_probes import prove_declared_probes
from yoke_harness.ssh_mac_full_reset import execute_full_test_mac_reset
from yoke_harness.ssh_mac_golden_capture import capture_golden_baseline
from yoke_harness.ssh_mac_terminal_bridge_diagnose import (
    diagnose_terminal_app_control,
)
from yoke_harness.ssh_mac_gui_session import (
    classify_macos_session_context_failure,
    run_terminal_app_command,
)
from yoke_harness.ssh_mac_terminal_bridge_check import (
    verify_terminal_app_control,
)
from yoke_harness.test_machine_types import HostActionResult


SSH_OPTIONS = (
    "StrictHostKeyChecking=accept-new",
    "UserKnownHostsFile=/dev/null",
    "ConnectTimeout=10",
    "BatchMode=yes",
)


class SshMacTransport:
    """Bounded SSH operations shared by Test Machine client adapters."""

    def __init__(
        self,
        *,
        settings: Mapping[str, str],
        key_path: str | Path,
    ) -> None:
        self._key_path = Path(key_path)
        self._host = str(settings["host"])
        self._user = str(settings["user"])
        self.golden_baseline_path = (
            str(settings.get("golden_baseline_path") or "") or None
        )
        facts = self._host_facts()
        self.home = str(facts["home"])
        self.shell = str(facts["shell"])
        self.xdg_bin_home = str(facts.get("xdg_bin_home") or "") or None
        path_env = {"HOME": self.home, "SHELL": self.shell}
        if self.xdg_bin_home:
            path_env["XDG_BIN_HOME"] = self.xdg_bin_home
        self.path_state: PathStateContract = resolve_path_state_contract(env=path_env)

    def _ssh_argv(self, command: str) -> list[str]:
        return [
            "ssh",
            "-i",
            str(self._key_path),
            *[part for option in SSH_OPTIONS for part in ("-o", option)],
            f"{self._user}@{self._host}",
            command,
        ]

    def _run(
        self,
        command: str,
        *,
        input_text: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        argv = self._ssh_argv(command)
        try:
            return subprocess.run(
                argv,
                input=input_text,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return subprocess.CompletedProcess(
                argv,
                returncode=124,
                stdout="",
                stderr="host_control subprocess unavailable",
            )

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
            raise RuntimeError("host_control connection failed")
        values = result.stdout.split("\n")
        if len(values) < 3 or not values[0]:
            raise RuntimeError("host_control returned incomplete host facts")
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
        ok, evidence, error_code = verify_terminal_app_control(
            self._run,
            expected_console_user=self._user,
        )
        return HostActionResult(
            ok=ok,
            error_code=error_code,
            evidence={"terminal_backend": "Terminal.app", **evidence},
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

    def run_remote_command(
        self,
        command: str,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        """Run one prepared shell command on the host."""
        return self._run(command, timeout=timeout)

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
        return execute_full_test_mac_reset(
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

    def probe_path(self, surface: str) -> Sequence[str]:
        flag = "-lic" if surface == "login" else "-c"
        probe = "printf '%s' \"$PATH\""
        result = self._run(
            f"{shlex.quote(self.shell)} {flag} {shlex.quote(probe)}",
            timeout=20,
        )
        if result.returncode:
            raise RuntimeError(f"host_control {surface} PATH probe failed")
        return tuple(entry for entry in result.stdout.strip().split(":") if entry)

    def run_command(
        self,
        argv: Sequence[str],
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        """Run bounded argv through SSH or the declared GUI session."""
        normalized = tuple(str(value) for value in argv)
        if not normalized or any(not value for value in normalized):
            raise ValueError("host_control command requires non-empty argv")
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
