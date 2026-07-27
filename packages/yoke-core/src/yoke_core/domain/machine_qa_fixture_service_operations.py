"""Service, report, terminal, and assertion Machine QA fixture handlers."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from yoke_core.domain.machine_qa_fixture_assets import (
    FAKE_API_SERVER_PATH,
    FAKE_API_SERVER_SCRIPT,
    FAKE_SERVICE_VARIANTS,
    FIXTURE_ROOT,
    SERVICE_MANAGER_PATH,
    SERVICE_MANAGER_SCRIPT,
    SOURCE_CHECKOUT_ASSERTION_PATH,
    SOURCE_CHECKOUT_ASSERTION_SCRIPT,
    build_apply_resume_report,
)
from yoke_core.domain.machine_qa_fixture_runtime import (
    RemoteFixtureFailure,
    ServiceCleanup,
)


class MachineQaFixtureServiceOperations:
    """Manage fake services and output-sensitive fixture operations."""

    def _yoke_api(self, parameters: Mapping[str, Any]) -> None:
        port = int(parameters["port"])
        variant = FAKE_SERVICE_VARIANTS[(str(parameters["profile"]), port)]
        previous = self._services.get(port)
        if previous is not None:
            self._stop_service(previous)
            self._services.pop(port, None)
        self._upload(
            FAKE_API_SERVER_PATH,
            FAKE_API_SERVER_SCRIPT,
            mode=0o700,
        )
        self._upload(
            SERVICE_MANAGER_PATH,
            SERVICE_MANAGER_SCRIPT,
            mode=0o700,
        )
        service_root = f"{FIXTURE_ROOT}/services"
        profile_path = f"{service_root}/{port}-{parameters['profile']}.json"
        identity_path = f"{service_root}/{port}.identity.json"
        log_path = f"{service_root}/{port}.log"
        identity = f"yoke-machine-qa:{parameters['profile']}:{port}"
        self._upload(
            profile_path,
            json.dumps(dict(variant.payload), sort_keys=True) + "\n",
            mode=0o600,
        )
        self._run(
            self._installed_yoke_python(
                SERVICE_MANAGER_PATH,
                "start",
                FAKE_API_SERVER_PATH,
                profile_path,
                port,
                identity_path,
                identity,
                log_path,
            ),
            timeout=30,
        )
        self._services[port] = ServiceCleanup(
            identity_path=identity_path,
            identity=identity,
        )

    def _stop_service(self, cleanup: ServiceCleanup) -> None:
        self._upload(
            SERVICE_MANAGER_PATH,
            SERVICE_MANAGER_SCRIPT,
            mode=0o700,
        )
        self._run(
            self._installed_yoke_python(
                SERVICE_MANAGER_PATH,
                "stop",
                cleanup.identity_path,
                cleanup.identity,
            ),
            timeout=20,
        )

    def _apply_resume_report(
        self,
        parameters: Mapping[str, Any],
    ) -> None:
        report_path = (
            f"{self.home}/.yoke/onboarding-runs/apply-reports/"
            f"{parameters['run_id']}.json"
        )
        payload = build_apply_resume_report(parameters, home=self.home)
        self._upload(
            report_path,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            mode=0o600,
        )

    def _terminal_size(self, parameters: Mapping[str, Any]) -> None:
        if self._prepare_terminal_size is None:
            raise RemoteFixtureFailure
        try:
            self._prepare_terminal_size(
                int(parameters["columns"]),
                int(parameters["rows"]),
            )
        except Exception as exc:
            raise RemoteFixtureFailure from exc

    def _checkout_state_assert(
        self,
        parameters: Mapping[str, Any],
    ) -> None:
        self._upload(
            SOURCE_CHECKOUT_ASSERTION_PATH,
            SOURCE_CHECKOUT_ASSERTION_SCRIPT,
            mode=0o700,
        )
        self._run(
            self._installed_yoke_python(
                SOURCE_CHECKOUT_ASSERTION_PATH,
                parameters["checkout_path"],
                parameters["apply_report_path"],
                parameters["expected_origin"],
                parameters["expected_branch"],
            ),
            timeout=120,
        )


__all__ = ["MachineQaFixtureServiceOperations"]
