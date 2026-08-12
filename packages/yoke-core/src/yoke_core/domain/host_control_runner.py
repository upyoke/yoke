"""Approved adapter boundary for secret-consuming host_control execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, Sequence

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
    TEST_MACHINE_SECRET_KEYS,
)
from yoke_harness.test_machine_types import HostActionResult

from yoke_core.domain import db_backend
from yoke_core.domain.capability_machine_secrets import (
    machine_capability_secret_path,
    read_machine_capability_secret,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.test_machine_capability import (
    TestMachineCapabilityError,
    validate_test_machine_settings,
)

if TYPE_CHECKING:
    from yoke_core.domain.machine_qa_fixture_operations import (
        MachineQaFixtureOperationRunner,
    )


class HostControl(Protocol):
    """Structured operations an approved controlled-host adapter implements."""

    home: str
    shell: str
    xdg_bin_home: str | None

    def check_connection(self) -> HostActionResult: ...

    def check_terminal_bridge(self) -> HostActionResult: ...

    def read_text(self, path: str) -> str | None: ...

    def write_text(self, path: str, content: str) -> None: ...

    def create_fixture_operation_runner(
        self,
    ) -> "MachineQaFixtureOperationRunner": ...

    def reset_installer_test_host(self) -> HostActionResult: ...

    def probe_path(self, surface: str) -> Sequence[str]: ...

    def run_terminal_case(
        self,
        *,
        entry_surface: str,
        required_completion: str,
        steps: Sequence[Mapping[str, Any]],
        capture_checkpoints: Sequence[str],
    ) -> HostActionResult: ...

    def run_terminal_recipe(
        self,
        *,
        entry_surface: str,
        required_completion: str,
        config: Mapping[str, Any],
        progress_callback: Callable[[], None] | None = None,
        allowed_operator_urls: Sequence[str] = (),
    ) -> HostActionResult: ...

    def run_machine_assertions(
        self,
        assertions: Sequence[Mapping[str, Any]],
    ) -> HostActionResult: ...


@dataclass(frozen=True, repr=False)
class TestMachineMaterial:
    """Capability material passed only to an approved adapter factory.

    The ``TestMachine`` prefix names the QA test-machine capability, not a
    pytest test case. ``__test__ = False`` opts the class out of pytest's
    ``Test*`` naming heuristic so importing it into a test module does not
    raise ``PytestCollectionWarning``.
    """

    __test__ = False

    project_id: int
    project: str
    settings: dict[str, str]
    secrets: dict[str, str]
    secret_paths: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            "TestMachineMaterial("
            f"project_id={self.project_id}, project={self.project!r}, "
            f"settings={self.settings!r}, secret_keys={sorted(self.secrets)!r})"
        )


@dataclass(frozen=True)
class TestMachineContract:
    """Secret-free capability settings issued by the control plane.

    ``__test__ = False`` for the same reason as ``TestMachineMaterial``.
    """

    __test__ = False

    project_id: int
    project: str
    settings: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project": self.project,
            "settings": dict(self.settings),
        }


HostControlFactory = Callable[[TestMachineMaterial], HostControl]
_factory: HostControlFactory | None = None


def register_host_control_factory(factory: HostControlFactory) -> None:
    """Register the process-local approved host adapter composition."""
    global _factory
    _factory = factory


def clear_host_control_factory() -> None:
    """Remove the process-local adapter composition (tests and shutdown)."""
    global _factory
    _factory = None


def load_test_machine_contract(
    conn: Any,
    *,
    project: str,
) -> TestMachineContract:
    """Resolve server-authoritative settings without touching local secrets."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise TestMachineCapabilityError(f"project {project!r} not found")
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id={marker} AND type={marker}",
        (identity.id, TEST_MACHINE_CAPABILITY),
    ).fetchone()
    if row is None:
        raise TestMachineCapabilityError(
            f"project {identity.slug!r} has no test-machine capability"
        )
    import json

    settings = validate_test_machine_settings(json.loads(str(row[0])))
    return TestMachineContract(
        project_id=int(identity.id),
        project=identity.slug,
        settings=settings,
    )


def materialize_test_machine_contract(
    contract: TestMachineContract | Mapping[str, Any],
) -> TestMachineMaterial:
    """Attach the one required credential on the executing client machine."""
    if isinstance(contract, TestMachineContract):
        normalized = contract
    else:
        try:
            normalized = TestMachineContract(
                project_id=int(contract["project_id"]),
                project=str(contract["project"]),
                settings=validate_test_machine_settings(
                    dict(contract["settings"]),
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TestMachineCapabilityError(
                "host-control contract contains invalid project settings"
            ) from exc
    secrets: dict[str, str] = {}
    secret_paths: dict[str, str] = {}
    missing: list[str] = []
    for key in sorted(TEST_MACHINE_SECRET_KEYS):
        value = read_machine_capability_secret(
            normalized.project,
            TEST_MACHINE_CAPABILITY,
            key,
        )
        if value is None:
            missing.append(key)
        else:
            secrets[key] = value
            secret_paths[key] = str(
                machine_capability_secret_path(
                    normalized.project,
                    TEST_MACHINE_CAPABILITY,
                    key,
                )
            )
    if missing:
        raise TestMachineCapabilityError(
            "test-machine is missing machine-local credential references: "
            + ", ".join(missing)
        )
    return TestMachineMaterial(
        project_id=normalized.project_id,
        project=normalized.project,
        settings=normalized.settings,
        secrets=secrets,
        secret_paths=secret_paths,
    )


def materialize_test_machine(conn: Any, *, project: str) -> TestMachineMaterial:
    """Resolve settings and required machine-local secrets for local execution."""
    return materialize_test_machine_contract(
        load_test_machine_contract(conn, project=project),
    )


def resolve_contract_host_control(
    contract: TestMachineContract | Mapping[str, Any],
) -> tuple[HostControl, TestMachineMaterial]:
    """Materialize a server-issued contract on the credential-owning machine."""
    if _factory is None:
        raise TestMachineCapabilityError(
            "host_control runner is not registered on this machine"
        )
    material = materialize_test_machine_contract(contract)
    return _factory(material), material


def resolve_host_control(
    conn: Any, *, project: str
) -> tuple[HostControl, TestMachineMaterial]:
    """Materialize the configured adapter or fail closed."""
    return resolve_contract_host_control(
        load_test_machine_contract(conn, project=project),
    )


__all__ = [
    "HostActionResult",
    "HostControl",
    "HostControlFactory",
    "TestMachineContract",
    "TestMachineMaterial",
    "clear_host_control_factory",
    "load_test_machine_contract",
    "materialize_test_machine",
    "materialize_test_machine_contract",
    "register_host_control_factory",
    "resolve_contract_host_control",
    "resolve_host_control",
]
