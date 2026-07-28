"""Machine-state setup handlers for Machine QA fixtures."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from yoke_contracts.machine_qa_execution import HOST_TEST_COMMAND

from yoke_core.domain.machine_qa_fixture_assets import (
    FIXTURE_ROOT,
    STARTUP_MARKER_ASSERTION_PATH,
    STARTUP_MARKER_ASSERTION_SCRIPT,
)
from yoke_core.domain.machine_qa_fixture_runtime import (
    RemoteFixtureFailure,
    shell_command,
)


_SYNTHETIC_STAGE_TOKEN = "fake-stage-" + "token"
_SYNTHETIC_PROD_TOKEN = "fake-prod-" + "token"


class MachineQaFixtureMachineOperations:
    """Implement machine-local fixture state transitions."""

    def _workspace_reset(self, parameters: Mapping[str, Any]) -> None:
        self._delete(*parameters["paths"])

    def _current_release(self, parameters: Mapping[str, Any]) -> None:
        if parameters["remove_existing_launcher"]:
            self._delete(self._yoke_bin())
        installer = f"{FIXTURE_ROOT}/install/{parameters['evidence_name']}-install"
        self._run(shell_command("/bin/mkdir", "-p", f"{FIXTURE_ROOT}/install"))
        self._run(
            shell_command(
                "/usr/bin/curl",
                "-fsSL",
                f"{parameters['base_url']}/install",
                "-o",
                installer,
            ),
            timeout=300,
        )
        self._run(
            shell_command(
                "/usr/bin/env",
                f"YOKE_INSTALL_BASE_URL={parameters['base_url']}",
                f"YOKE_CHANNEL={parameters['channel']}",
                "YOKE_INSTALL_YES=1",
                "YOKE_NO_ONBOARD=1",
                "/bin/sh",
                installer,
                "--yes",
                "--no-onboard",
            ),
            timeout=1200,
        )

    def _product_state_reset(self, parameters: Mapping[str, Any]) -> None:
        self._delete(*parameters["paths"])

    def _path_prepare(self, _parameters: Mapping[str, Any]) -> None:
        self._run(
            shell_command(self._yoke_bin(), "path", "fix", "--yes"),
            timeout=300,
        )

    def _path_idempotence(self, parameters: Mapping[str, Any]) -> None:
        for _ in range(parameters["repeats"]):
            self._run(
                shell_command(self._yoke_bin(), "path", "fix", "--yes"),
                timeout=300,
            )
        self._upload(
            STARTUP_MARKER_ASSERTION_PATH,
            STARTUP_MARKER_ASSERTION_SCRIPT,
            mode=0o700,
        )
        startup_paths = [
            self._resolve_path(path) for path in parameters["startup_files"]
        ]
        self._run(
            self._installed_yoke_python(
                STARTUP_MARKER_ASSERTION_PATH,
                parameters["managed_block_marker"],
                parameters["expected_block_count"],
                *startup_paths,
            )
        )

    def _connection_prepare(self, parameters: Mapping[str, Any]) -> None:
        token_path = self._resolve_path(parameters["token_path"])
        payload = self._machine_config(
            active_env=parameters["active_env"],
            connections={
                parameters["active_env"]: {
                    "transport": parameters["transport"],
                    "prod": False,
                    "api_url": parameters["api_url"],
                    "credential_source": {
                        "kind": "token_file",
                        "path": token_path,
                    },
                }
            },
        )
        self._write_machine_config(payload)

    def _connection_restore(self, parameters: Mapping[str, Any]) -> None:
        token_path = self._resolve_path(parameters["token_path"])
        config_path = f"{self.home}/.yoke/config.json"
        if (
            parameters["require_existing_token"]
            and self._invoke(shell_command(HOST_TEST_COMMAND, "-f", token_path)) != 0
        ):
            raise RemoteFixtureFailure
        self._run(
            shell_command(
                self._yoke_bin(),
                "connection",
                "set",
                parameters["active_env"],
                "--transport",
                "https",
                "--api-url",
                parameters["api_url"],
                "--token-file",
                token_path,
                "--non-prod",
                "--config",
                config_path,
            ),
            timeout=300,
        )
        self._run(
            shell_command(
                self._yoke_bin(),
                "env",
                "use",
                parameters["active_env"],
                "--config",
                config_path,
            )
        )

    def _connections_prepare(self, parameters: Mapping[str, Any]) -> None:
        connections = {}
        token_values = {
            "stage": _SYNTHETIC_STAGE_TOKEN,
            "prod": _SYNTHETIC_PROD_TOKEN,
        }
        for name, raw in parameters["connections"].items():
            token_path = self._resolve_path(raw["token_path"])
            self._upload(
                token_path,
                token_values[name] + "\n",
                mode=0o600,
            )
            connections[name] = {
                "transport": raw["transport"],
                "prod": raw["prod"],
                "api_url": raw["api_url"],
                "credential_source": {
                    "kind": "token_file",
                    "path": token_path,
                },
            }
        self._write_machine_config(
            self._machine_config(
                active_env=parameters["active_env"],
                connections=connections,
            )
        )

    def _machine_config(
        self,
        *,
        active_env: str,
        connections: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "active_env": active_env,
            "temp_root": "~/.yoke/tmp",
            "cache_dir": "~/.yoke/cache",
            "connections": dict(connections),
        }

    def _write_machine_config(self, payload: Mapping[str, Any]) -> None:
        self._upload(
            f"{self.home}/.yoke/config.json",
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            mode=0o600,
        )


__all__ = ["MachineQaFixtureMachineOperations"]
