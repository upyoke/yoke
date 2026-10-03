"""SSH operations for persistent, non-root Linux test machines."""

from __future__ import annotations

import base64
import json
import shlex
import subprocess
from typing import Any, Mapping, Sequence

from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT
from yoke_contracts.machine_qa_failures import (
    HostControlLocalError,
    bounded_machine_qa_diagnostic,
)
from yoke_harness.ssh_host_baselines import SshHostBaselines
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport
from yoke_harness.ssh_linux_baseline import (
    archive_operation,
    capture_linux_golden,
    prove_linux_probes,
)
from yoke_harness.ssh_linux_terminal import (
    diagnose_linux_terminal,
)
from yoke_harness.ssh_mac_full_reset_contract import GOLDEN_PROBES_SUFFIX
from yoke_harness.ssh_tool_resolution import probe_reset_tools, tools_present
from yoke_harness.test_machine_types import HostActionResult


class SshLinuxHostOperations(SshHostBaselines, SshTestMachineTransport):
    """Home restore, user probes and tmux on one credential-bound SSH host."""

    @classmethod
    def from_contract(cls, contract):
        from yoke_cli.config.capability_secrets import read_machine_capability_secret
        from yoke_contracts.machine_config.test_machine import (
            test_machine_capability_type,
        )
        from yoke_contracts.machine_config.desktop_access import DESKTOP_PASSWORD_KEY
        from yoke_harness.linux_desktop_state import RDP_PORT

        control = super().from_contract(contract)
        control.desktop_password = read_machine_capability_secret(
            contract.project,
            test_machine_capability_type(contract.settings["resource_name"]),
            DESKTOP_PASSWORD_KEY,
        )
        control.desktop_port = int(contract.settings.get("desktop_port", RDP_PORT))
        if control.desktop_password:
            control.secret_values = (*control.secret_values, control.desktop_password)
        return control

    def capture_screenshot(self):
        from yoke_harness.ssh_machine_screenshot import capture_desktop

        return capture_desktop(self)

    def _host_facts(self) -> dict[str, Any]:
        script = "import os,json,platform; print(json.dumps(dict(home=os.environ['HOME'],shell=os.environ.get('SHELL','/bin/bash'),xdg_bin_home=os.environ.get('XDG_BIN_HOME'),uid=os.getuid(),os=platform.system())))"
        result = self._run(shlex.join(["/usr/bin/python3", "-c", script]), timeout=20)
        if result.returncode in (124, 255):
            raise HostControlLocalError(
                code="ssh_unavailable",
                phase="host_facts_ssh",
                detail="SSH could not read the test user's host facts.",
                recovery_hint="Verify the registered host's current address, running state, SSH listener and authorized key before retrying.",
                exit_code=result.returncode,
                stderr=bounded_machine_qa_diagnostic(result.stderr, self.secret_values),
            )
        try:
            facts = json.loads(result.stdout)
            valid = (
                facts["os"] == "Linux"
                and facts["uid"] != 0
                and facts["home"].startswith("/")
            )
        except (ValueError, KeyError, TypeError):
            valid = False
        if result.returncode or not valid:
            raise HostControlLocalError(
                code="linux_test_user_required",
                phase="host_facts_ssh",
                detail="Linux Test Machines require a non-root SSH user and Python 3.",
                recovery_hint="Declare the provisioned non-root user's host and key; install Python 3 and retry.",
            )
        return facts

    def check_connection(self) -> HostActionResult:
        result = self._run("/usr/bin/true", timeout=20)
        return HostActionResult(
            result.returncode == 0,
            {
                "transport": "ssh",
                "host": self._host,
                "user": self._user,
                "os": "linux",
                "runner_materialized": result.returncode == 0,
            },
            None if result.returncode == 0 else "ssh_unavailable",
        )

    def check_terminal_bridge(self) -> HostActionResult:
        return diagnose_linux_terminal(self)

    def diagnose_terminal_bridge(self) -> HostActionResult:
        return diagnose_linux_terminal(self)

    def capture_golden_baseline(
        self, destination: str, *, probes_document: str | None = None
    ) -> HostActionResult:
        return capture_linux_golden(self, destination, probes_document)

    def reset_installer_test_host(self) -> HostActionResult:
        if not self.golden_baseline_path:
            return HostActionResult(
                False,
                {
                    "recovery": "Capture a golden outside the home, then set golden_baseline_path."
                },
                "golden_baseline_not_declared",
            )
        restored = archive_operation(self, "reset", self.golden_baseline_path)
        if not restored.ok:
            return restored
        observed = probe_reset_tools(self)
        failed = any(
            probe["state"] == "probe-failed"
            for surface in observed.values()
            for probe in surface.values()
        )
        present = tools_present(observed)
        absent = present is False and not failed
        return HostActionResult(
            absent,
            {
                **restored.evidence,
                "path_state": {
                    "launcher_present": tools_present(observed, ("yoke",)),
                    "yoke_tools_resolve": present,
                },
                "tool_resolution": observed,
                **(
                    {
                        "recovery": "Inspect tool_resolution for the failed surface/tool and repair its shell or SSH probe before retrying reset."
                    }
                    if failed
                    else {
                        "recovery": "Inspect tool_resolution for surviving executable paths before retrying the sealed baseline."
                    }
                    if not absent
                    else {}
                ),
            },
            "reset_tool_probe_failed"
            if failed
            else None
            if absent
            else "reset_absence_not_proved",
        )

    def prove_user_equivalent(self) -> HostActionResult:
        document = (
            self.read_remote_text(
                (self.golden_baseline_path or "") + GOLDEN_PROBES_SUFFIX
            )
            if self.golden_baseline_path
            else None
        )
        if document is None:
            return HostActionResult(
                False,
                {
                    "recovery": "Capture a golden with the standard OS checks before verification."
                },
                "baseline_probes_not_declared",
            )
        return prove_linux_probes(self, document)

    def upload_remote_text(self, path: str, content: str) -> None:
        if not self._upload_bytes(path, content.encode("utf-8")):
            raise RuntimeError(
                "linux_host_file_write_failed: check owner-only path permissions"
            )

    def read_remote_text(self, path: str) -> str | None:
        script = "import pathlib,sys,base64; p=pathlib.Path(sys.argv[1]); assert p.is_absolute() and not p.is_symlink(); print(base64.b64encode(p.read_bytes()).decode() if p.is_file() else '')"
        result = self._run(shlex.join(["/usr/bin/python3", "-c", script, path]))
        if result.returncode:
            raise RuntimeError(
                "linux_host_file_read_failed: check the declared regular file"
            )
        return (
            base64.b64decode(result.stdout).decode("utf-8")
            if result.stdout.strip()
            else None
        )

    def _upload_bytes(self, path: str, content: bytes) -> bool:
        script = "import pathlib,sys,os,base64; p=pathlib.Path(sys.argv[1]); assert p.is_absolute() and not p.is_symlink(); p.parent.mkdir(parents=True,exist_ok=True); f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600); os.fchmod(f,0o600); stream=os.fdopen(f,'wb'); stream.write(base64.b64decode(sys.stdin.read())); stream.close()"
        return (
            self._run(
                shlex.join(["/usr/bin/python3", "-c", script, path]),
                input_text=base64.b64encode(content).decode("ascii"),
            ).returncode
            == 0
        )

    def run_command(
        self,
        argv: Sequence[str],
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        """Run SSH argv with a non-empty executable and preserve empty option values."""
        if not argv or not str(argv[0]):
            raise ValueError("host_control command requires a non-empty executable")
        if required_session_context == GUI_SESSION_CONTEXT:
            from yoke_harness.linux_desktop_session import desktop_command

            try:
                return desktop_command(self, list(argv), timeout=timeout)
            except RuntimeError as exc:
                return subprocess.CompletedProcess(list(argv), 69, "", str(exc))
        if required_session_context is not None:
            raise ValueError(
                f"unknown host_control session context {required_session_context!r}"
            )
        return self._run(shlex.join(argv), timeout=timeout)

    def run_machine_assertions(
        self, assertions: Sequence[Mapping[str, Any]]
    ) -> HostActionResult:
        rows = []
        for assertion in assertions:
            context = assertion.get("required_session_context")
            result = self.run_command(
                assertion["argv"], required_session_context=context
            )
            expected = int(assertion.get("expected_exit", 0))
            rows.append(
                {
                    "argv": assertion["argv"],
                    "expected_exit": expected,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "execution_context": context or "ssh",
                    **(
                        {"desktop_session": result.desktop_session}
                        if hasattr(result, "desktop_session")
                        else {}
                    ),
                }
            )
            if result.returncode != expected:
                return HostActionResult(
                    False,
                    {"assertions": rows},
                    "machine_assertion_failed",
                )
        return HostActionResult(
            True, {"assertions": rows, "secret_scan": "pending-redaction"}
        )
