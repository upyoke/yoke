"""Shared fresh and installed shell baselines for SSH test machines."""

from __future__ import annotations

import shlex

from yoke_contracts.api_urls import (
    DISTRIBUTION_BASE_URL_ENV,
    DISTRIBUTION_STAGE_URL,
)
from yoke_contracts.machine_qa_execution import (
    HOST_TEST_COMMAND,
    HOST_BASELINES,
)
from yoke_harness.ssh_mac_baseline_probes import reach_user_equivalent_baseline
from yoke_harness.ssh_mac_full_reset_contract import INSTALLER_TEMP_PATH
from yoke_harness.test_machine_types import HostActionResult


_CURRENT_RELEASE_CHANNEL = "latest"
_INSTALLER_CHANNEL_ENV = "YOKE_CHANNEL"
_INSTALLER_CONFIRM_ENV = "YOKE_INSTALL_YES"
_INSTALLER_NO_ONBOARD_ENV = "YOKE_NO_SETUP"


class SshHostBaselines:
    """Restore OS-owned golden state before preparing shell PATH surfaces."""

    def reach_baseline(self, name: str) -> HostActionResult:
        """Reach one server-approved verification baseline."""
        if name == HOST_BASELINES[0]:
            return reach_user_equivalent_baseline(self)
        if name == HOST_BASELINES[1]:
            return self._reach_shell_preconfigured()
        raise ValueError(f"unknown host baseline {name!r}")

    def _reach_shell_preconfigured(self) -> HostActionResult:
        name = HOST_BASELINES[1]
        reset = reach_user_equivalent_baseline(self)
        if not reset.ok:
            return HostActionResult(
                False,
                {
                    "operation": name,
                    "reset": reset.evidence,
                    "case_started": False,
                },
                reset.error_code,
            )
        setup = self._install_current_release(name)
        if not setup.ok:
            return HostActionResult(
                False,
                {
                    "operation": name,
                    "reset": reset.evidence,
                    "setup_operations": setup.evidence.get("operations", []),
                    "verified_property": self._shell_baseline_property(),
                },
                setup.error_code,
            )
        try:
            tool_dir = self.path_state.tool_bin_dir
            observed = {
                surface: list(self.probe_path(surface)) for surface in ("login", "ssh")
            }
            launcher = self.path_state.yoke_bin
            launcher_check = self.run_machine_assertions(
                [{"argv": [HOST_TEST_COMMAND, "-x", launcher]}]
            )
        except Exception:
            return HostActionResult(
                False,
                {
                    "operation": name,
                    "reset": reset.evidence,
                    "setup_operations": setup.evidence.get("operations", []),
                    "verified_property": self._shell_baseline_property(),
                },
                "baseline_operation_failed",
            )
        path_checks = {
            surface: tool_dir in entries for surface, entries in observed.items()
        }
        ok = launcher_check.ok and all(path_checks.values())
        return HostActionResult(
            ok,
            {
                "operation": name,
                "reset": reset.evidence,
                "setup_operations": setup.evidence.get("operations", []),
                "cleanup_attempts": [{"outcome": "passed", "operations": []}],
                "tool_bin_dir": tool_dir,
                "launcher_executable": launcher_check.ok,
                "path_state": {
                    "launcher": launcher,
                    "launcher_present": launcher_check.ok,
                    "tool_bin_dir": tool_dir,
                    "login_path_present": path_checks["login"],
                    "ssh_path_present": path_checks["ssh"],
                },
                "verified_property": self._shell_baseline_property(),
                "observed_present": path_checks,
            },
            None if ok else "baseline_verification_failed",
        )

    def _install_current_release(self, evidence_name: str) -> HostActionResult:
        operations: list[dict[str, str]] = []
        operation_commands = (
            (
                "installer.current-release-prepare",
                (
                    (
                        shlex.join(
                            [
                                "/usr/bin/curl",
                                "-fsSL",
                                f"{DISTRIBUTION_STAGE_URL}/install",
                                "-o",
                                INSTALLER_TEMP_PATH,
                            ]
                        ),
                        300,
                    ),
                    (
                        shlex.join(
                            [
                                "/usr/bin/env",
                                f"{DISTRIBUTION_BASE_URL_ENV}={DISTRIBUTION_STAGE_URL}",
                                f"{_INSTALLER_CHANNEL_ENV}={_CURRENT_RELEASE_CHANNEL}",
                                f"{_INSTALLER_CONFIRM_ENV}=1",
                                f"{_INSTALLER_NO_ONBOARD_ENV}=1",
                                "/bin/sh",
                                INSTALLER_TEMP_PATH,
                                "--yes",
                                "--no-setup",
                            ]
                        ),
                        1200,
                    ),
                ),
            ),
            (
                "machine.path-prepare",
                (
                    (
                        shlex.join(
                            [
                                self.path_state.yoke_bin,
                                "path",
                                "fix",
                                "--yes",
                            ]
                        ),
                        300,
                    ),
                ),
            ),
        )
        for operation_id, commands in operation_commands:
            for command, timeout in commands:
                result = self._run(command, timeout=timeout)
                if not result.returncode:
                    continue
                operations.append({"id": operation_id, "outcome": "failed"})
                return HostActionResult(
                    False,
                    {"operations": operations},
                    "fixture_operation_failed",
                )
            operations.append({"id": operation_id, "outcome": "passed"})
        return HostActionResult(
            True,
            {
                "operations": operations,
                "evidence_name": evidence_name,
            },
        )

    @staticmethod
    def _shell_baseline_property() -> str:
        return (
            "current Yoke launcher is executable and its tool directory is "
            "present in login and SSH shell PATH"
        )
