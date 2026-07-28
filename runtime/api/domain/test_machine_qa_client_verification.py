"""Client-safe Test Machine verification execution coverage."""

from __future__ import annotations

import json
import shlex
import subprocess
from types import SimpleNamespace

from yoke_contracts.api_urls import (
    DISTRIBUTION_BASE_URL_ENV,
    DISTRIBUTION_STAGE_URL,
)
from yoke_contracts.machine_qa_execution import (
    VERIFICATION_BASELINES,
    VERIFICATION_CHECKS,
    issue_execution_contract,
)
from yoke_harness.ssh_mac_full_reset_contract import INSTALLER_TEMP_PATH
from yoke_harness.ssh_mac_verification import SshMacVerificationControl
from yoke_harness.test_machine_types import HostActionResult
from yoke_harness.test_machine_verification import (
    execute_verification_contract,
)


def _verification_contract() -> dict[str, object]:
    return issue_execution_contract(
        operation="verify",
        lease_id=19,
        lease_key="QA_HOST:mac-mini-lab",
        project_id=1,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "",
        },
        checks=list(VERIFICATION_CHECKS),
        baselines=list(VERIFICATION_BASELINES),
    ).model_dump(mode="json")


def test_client_verification_runs_only_the_server_contract_and_redacts() -> None:
    calls: list[str] = []

    class Control:
        secret_values = ("top-secret",)

        def check_connection(self) -> HostActionResult:
            calls.append("connection")
            return HostActionResult(
                True,
                {"credential_echo": "top-secret"},
            )

        def check_terminal_bridge(self) -> HostActionResult:
            calls.append("terminal_bridge")
            return HostActionResult(True, {"terminal_control": True})

        def reach_baseline(self, name: str) -> HostActionResult:
            calls.append(name)
            return HostActionResult(True, {"operation": name})

    submission = execute_verification_contract(
        _verification_contract(),
        control_factory=lambda _contract: Control(),
    )

    assert calls == [*VERIFICATION_CHECKS, *VERIFICATION_BASELINES]
    assert submission.payload["status"] == "verified"
    encoded = json.dumps(submission.payload)
    assert "top-secret" not in encoded
    assert "[REDACTED]" in encoded


def test_client_shell_baseline_uses_the_published_installer_recipe() -> None:
    commands: list[tuple[str, int]] = []

    def run(
        command: str,
        *,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        commands.append((command, timeout))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    control = SshMacVerificationControl.__new__(SshMacVerificationControl)
    control.path_state = SimpleNamespace(
        yoke_bin="/Users/tester/.local/bin/yoke",
    )
    control._run = run

    result = control._install_current_release(VERIFICATION_BASELINES[1])

    assert result.ok
    assert result.evidence["operations"] == [
        {
            "id": "installer.current-release-prepare",
            "outcome": "passed",
        },
        {"id": "machine.path-prepare", "outcome": "passed"},
    ]
    argv = [shlex.split(command) for command, _timeout in commands]
    assert argv[0] == [
        "/usr/bin/curl",
        "-fsSL",
        f"{DISTRIBUTION_STAGE_URL}/install",
        "-o",
        INSTALLER_TEMP_PATH,
    ]
    assert argv[1] == [
        "/usr/bin/env",
        f"{DISTRIBUTION_BASE_URL_ENV}={DISTRIBUTION_STAGE_URL}",
        "YOKE_CHANNEL=latest",
        "YOKE_INSTALL_YES=1",
        "YOKE_NO_ONBOARD=1",
        "/bin/sh",
        INSTALLER_TEMP_PATH,
        "--yes",
        "--no-onboard",
    ]
    assert argv[2] == [
        "/Users/tester/.local/bin/yoke",
        "path",
        "fix",
        "--yes",
    ]
    assert [timeout for _command, timeout in commands] == [300, 1200, 300]
