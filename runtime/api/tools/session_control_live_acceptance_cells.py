"""Named evidence paths for Fleet session-control acceptance cells."""

from __future__ import annotations

from dataclasses import dataclass

from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)


REGISTERED_SURFACE_PROOF_SCOPE = "registered_session_control_surface"
REGISTERED_BROKER_PROOF_SCOPE = "registered_broker_wake_route"
# Claude desktop create is a designed deferral: capability create=none and the
# adapter has no native create route. Identify proves the registered-surface
# path only, never operator-visible occupancy.
ACCEPTANCE_SURFACE_CELLS = (
    ("claude-cli", "create"),
    ("claude-desktop", "identify"),
    ("codex-cli", "create"),
    ("cursor-cli", "create"),
)
ACCEPTANCE_SURFACES = tuple(dict.fromkeys(row[0] for row in ACCEPTANCE_SURFACE_CELLS))


def acceptance_operation(surface: str, mode: str) -> str:
    if surface == "claude-desktop":
        return "message_active" if mode == "identify" else "create"
    return "message_stopped"


@dataclass(frozen=True)
class AcceptanceCell:
    surface: str
    expected_version: str
    mode: str
    session_id: str | None = None
    machine_id: str | None = None
    model: str | None = None
    acceptance_role: str = "surface"
    wake_route: str | None = None
    broker_session_id: str | None = None

    @property
    def wake_supported(self) -> bool:
        return surface_operation_supported(
            self.surface, self.expected_version, "message_stopped"
        )

    @property
    def route(self) -> str:
        return self.wake_route or ("direct" if self.wake_supported else "none")

    @property
    def proof_scope(self) -> str:
        return (
            REGISTERED_BROKER_PROOF_SCOPE
            if self.acceptance_role == "broker"
            else REGISTERED_SURFACE_PROOF_SCOPE
        )

    @property
    def cell_name(self) -> str:
        path = "broker" if self.acceptance_role == "broker" else self.mode
        return f"{self.surface}:{self.proof_scope}:{path}"

    @property
    def operation(self) -> str:
        return acceptance_operation(self.surface, self.mode)

    @property
    def acceptance_key(self) -> str:
        return self.cell_name


__all__ = [
    "ACCEPTANCE_SURFACE_CELLS",
    "ACCEPTANCE_SURFACES",
    "AcceptanceCell",
    "REGISTERED_BROKER_PROOF_SCOPE",
    "REGISTERED_SURFACE_PROOF_SCOPE",
    "acceptance_operation",
]
