"""SSH-backed implementation of the host-operation contract for a macOS box.

One class implements every operation a person can run against a mac-ssh test
machine -- verify, reset, capture a golden baseline, diagnose the terminal
bridge -- because they share a transport, a credential, and a lease, and
splitting them by operation would give four adapters four chances to disagree
about what the same host is.
"""

from __future__ import annotations

import shlex

from yoke_cli.config.capability_secrets import (
    machine_capability_secret_path,
    read_machine_capability_secret,
)
from yoke_contracts.api_urls import (
    DISTRIBUTION_BASE_URL_ENV,
    DISTRIBUTION_STAGE_URL,
)
from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
    TEST_MACHINE_SECRET_KEYS,
)
from yoke_contracts.machine_qa_execution import (
    HOST_TEST_COMMAND,
    HostControlExecutionContract,
    HOST_BASELINES,
)
from yoke_harness.ssh_mac_baseline_probes import reach_user_equivalent_baseline
from yoke_harness.ssh_mac_full_reset_contract import INSTALLER_TEMP_PATH
from yoke_harness.ssh_mac_transport import SshMacTransport
from yoke_harness.test_machine_types import HostActionResult


_CURRENT_RELEASE_CHANNEL = "latest"
_INSTALLER_CHANNEL_ENV = "YOKE_CHANNEL"
_INSTALLER_CONFIRM_ENV = "YOKE_INSTALL_YES"
_INSTALLER_NO_ONBOARD_ENV = "YOKE_NO_ONBOARD"


class SshMacHostOperations(SshMacTransport):
    """Credential-owning control for every operator-run mac-ssh operation."""

    def __init__(
        self,
        *,
        settings: dict[str, str],
        key_path: str,
        secret_values: tuple[str, ...],
    ) -> None:
        self.secret_values = secret_values
        super().__init__(settings=settings, key_path=key_path)

    @classmethod
    def from_contract(
        cls,
        contract: HostControlExecutionContract,
    ) -> "SshMacHostOperations":
        """Attach the one registered machine-local credential."""
        secrets: list[str] = []
        secret_paths: dict[str, str] = {}
        missing: list[str] = []
        for key in sorted(TEST_MACHINE_SECRET_KEYS):
            value = read_machine_capability_secret(
                contract.project,
                TEST_MACHINE_CAPABILITY,
                key,
            )
            if value is None:
                missing.append(key)
                continue
            secrets.append(value)
            secret_paths[key] = str(
                machine_capability_secret_path(
                    contract.project,
                    TEST_MACHINE_CAPABILITY,
                    key,
                )
            )
        if missing:
            raise RuntimeError(
                "test-machine is missing machine-local credential references: "
                + ", ".join(missing)
            )
        return cls(
            settings=contract.settings,
            key_path=secret_paths["ssh_private_key"],
            secret_values=tuple(secrets),
        )

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
                                "--no-onboard",
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


__all__ = ["SshMacHostOperations"]
