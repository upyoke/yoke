"""Execute the closed Machine QA setup and post-state operation registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from yoke_core.domain.host_control_runner import HostActionResult
from yoke_core.domain.machine_qa_fixture_credential_operations import (
    MachineQaFixtureCredentialOperations,
)
from yoke_core.domain.machine_qa_fixture_machine_operations import (
    MachineQaFixtureMachineOperations,
)
from yoke_core.domain.machine_qa_fixture_repository_operations import (
    MachineQaFixtureRepositoryOperations,
)
from yoke_core.domain.machine_qa_fixture_runtime import (
    MachineQaFixtureRuntime,
    RemoteCommandResult,
    RemoteFixtureFailure,
    RemoteRunner,
    RemoteTextUploader,
)
from yoke_core.domain.machine_qa_fixture_service_operations import (
    MachineQaFixtureServiceOperations,
)
from yoke_core.domain.machine_qa_fixture_validation import (
    MachineQaFixtureOperationError,
    validate_post_state_assertions,
    validate_setup_operations,
)


class MachineQaFixtureOperationRunner(
    MachineQaFixtureCredentialOperations,
    MachineQaFixtureMachineOperations,
    MachineQaFixtureRepositoryOperations,
    MachineQaFixtureServiceOperations,
    MachineQaFixtureRuntime,
):
    """Run validated fixture operations and own deterministic cleanup.

    ``run_remote`` can be wired to ``SshMacHostControl._run`` and
    ``upload_text`` to ``SshMacHostControl.write_text``. Callers must invoke
    :meth:`close` from a ``finally`` path; the context-manager form does so
    automatically. Failed cleanup remains pending and a later ``close`` retries
    it.
    """

    def execute_setup_operations(
        self,
        operations: Sequence[Mapping[str, Any]],
    ) -> HostActionResult:
        """Validate the whole setup batch, then execute it in order."""
        if not self._accepting:
            raise MachineQaFixtureOperationError("fixture runner is already closing")
        normalized = validate_setup_operations(operations)
        return self._execute_batch(normalized, self._setup_handlers())

    def execute_post_state_assertions(
        self,
        operations: Sequence[Mapping[str, Any]],
    ) -> HostActionResult:
        """Validate and run registered post-state assertions in order."""
        if not self._accepting:
            raise MachineQaFixtureOperationError("fixture runner is already closing")
        normalized = validate_post_state_assertions(operations)
        return self._execute_batch(normalized, self._post_handlers())

    def _execute_batch(
        self,
        operations: Sequence[tuple[str, dict[str, Any]]],
        handlers: Mapping[str, Callable[[Mapping[str, Any]], None]],
    ) -> HostActionResult:
        rows: list[dict[str, str]] = []
        for operation_id, parameters in operations:
            try:
                handlers[operation_id](parameters)
            except RemoteFixtureFailure:
                rows.append({"id": operation_id, "outcome": "failed"})
                return HostActionResult(
                    ok=False,
                    evidence={"operations": rows},
                    error_code="fixture_operation_failed",
                )
            rows.append({"id": operation_id, "outcome": "passed"})
        return HostActionResult(True, {"operations": rows})

    def _setup_handlers(
        self,
    ) -> Mapping[str, Callable[[Mapping[str, Any]], None]]:
        return {
            "fixture.apply-resume-report-prepare": self._apply_resume_report,
            "fixture.git-checkout-prepare": self._git_checkout,
            "fixture.git-remote-prepare": self._git_remote,
            "fixture.project-registrations-prepare": (self._project_registrations),
            "fixture.source-dev-checkout-prepare": self._source_dev_checkout,
            "fixture.source-dev-remote-prepare": self._source_dev_remote,
            "fixture.yoke-api-start": self._yoke_api,
            "installer-campaign.workspace-reset": self._workspace_reset,
            "installer.current-release-prepare": self._current_release,
            "installer.product-state-reset": self._product_state_reset,
            "machine.path-idempotence-prepare": self._path_idempotence,
            "machine.path-prepare": self._path_prepare,
            "machine.token-file-prepare": self._token_file,
            "machine.yoke-auth-clear": self._yoke_auth_clear,
            "machine.yoke-connection-prepare": self._connection_prepare,
            "machine.yoke-connection-restore": self._connection_restore,
            "machine.yoke-connections-prepare": self._connections_prepare,
            "terminal.size-prepare": self._terminal_size,
        }

    def _post_handlers(
        self,
    ) -> Mapping[str, Callable[[Mapping[str, Any]], None]]:
        return {
            "source-dev.checkout-state-assert": self._checkout_state_assert,
        }


__all__ = [
    "MachineQaFixtureOperationError",
    "MachineQaFixtureOperationRunner",
    "RemoteCommandResult",
    "RemoteRunner",
    "RemoteTextUploader",
    "validate_post_state_assertions",
    "validate_setup_operations",
]
