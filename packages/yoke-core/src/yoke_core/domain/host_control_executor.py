"""Approved adapter boundary for secret-consuming host_control execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
    TEST_MACHINE_SECRET_KEYS,
)

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


@dataclass(frozen=True)
class HostActionResult:
    """A secret-free executor result safe to persist as QA evidence."""

    ok: bool
    evidence: dict[str, Any]
    error_code: str | None = None


class HostControl(Protocol):
    """Structured operations an approved controlled-host adapter implements."""

    home: str
    shell: str
    xdg_bin_home: str | None

    def check_connection(self) -> HostActionResult: ...

    def check_terminal_bridge(self) -> HostActionResult: ...

    def read_text(self, path: str) -> str | None: ...

    def write_text(self, path: str, content: str) -> None: ...

    def probe_path(self, surface: str) -> Sequence[str]: ...

    def run_terminal_case(
        self,
        *,
        entry_surface: str,
        required_completion: str,
        steps: Sequence[Mapping[str, Any]],
        capture_checkpoints: Sequence[str],
    ) -> HostActionResult: ...

    def run_machine_assertions(
        self,
        assertions: Sequence[Mapping[str, Any]],
    ) -> HostActionResult: ...


@dataclass(frozen=True, repr=False)
class TestMachineMaterial:
    """Capability material passed only to an approved adapter factory."""

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


def materialize_test_machine(conn: Any, *, project: str) -> TestMachineMaterial:
    """Resolve settings and machine-local secrets without returning them to UI."""
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
    secrets: dict[str, str] = {}
    secret_paths: dict[str, str] = {}
    missing: list[str] = []
    for key in sorted(TEST_MACHINE_SECRET_KEYS):
        value = read_machine_capability_secret(
            identity.slug,
            TEST_MACHINE_CAPABILITY,
            key,
        )
        if value is None:
            missing.append(key)
        else:
            secrets[key] = value
            secret_paths[key] = str(machine_capability_secret_path(
                identity.slug,
                TEST_MACHINE_CAPABILITY,
                key,
            ))
    if missing:
        raise TestMachineCapabilityError(
            "test-machine is missing machine-local credential references: "
            + ", ".join(missing)
        )
    return TestMachineMaterial(
        project_id=int(identity.id),
        project=identity.slug,
        settings=settings,
        secrets=secrets,
        secret_paths=secret_paths,
    )


def resolve_host_control(conn: Any, *, project: str) -> tuple[HostControl, TestMachineMaterial]:
    """Materialize the configured adapter or fail closed."""
    if _factory is None:
        raise TestMachineCapabilityError(
            "host_control executor is not registered on this machine"
        )
    material = materialize_test_machine(conn, project=project)
    return _factory(material), material


__all__ = [
    "HostActionResult",
    "HostControl",
    "HostControlFactory",
    "TestMachineMaterial",
    "clear_host_control_factory",
    "materialize_test_machine",
    "register_host_control_factory",
    "resolve_host_control",
]
