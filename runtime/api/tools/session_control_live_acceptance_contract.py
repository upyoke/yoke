"""Closed input contract for deployed Fleet session-control acceptance."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
    surface_version_supported,
)


SCHEMA_VERSION = 2
ACCEPTANCE_SURFACES = (
    "claude-cli",
    "claude-desktop",
    "codex-cli",
    "codex-desktop",
    "cursor-cli",
)
_IDENTIFY_ONLY_SURFACES = frozenset({"claude-desktop"})
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_RELEASE_SHA = re.compile(r"^[0-9a-f]{40}$")
_SERVER_BUILD = re.compile(r"^[0-9a-f]{40}$")
_MATRIX_KEYS = frozenset({"schema", "project", "cells"})
_CELL_KEYS = frozenset(
    {
        "acceptance_role",
        "broker_session_id",
        "expected_version",
        "machine_id",
        "mode",
        "model",
        "session_id",
        "surface",
        "wake_route",
    }
)
_ACCEPTANCE_ROLES = frozenset({"surface", "broker"})
_WAKE_ROUTES = frozenset({"direct", "broker", "none"})


def acceptance_operation(surface: str) -> str:
    return "message_active" if surface == "claude-desktop" else "message_stopped"


def _version_acceptance_supported(surface: str, version: str) -> bool:
    operation = acceptance_operation(surface)
    return surface_operation_supported(surface, version, operation)


class AcceptanceContractError(ValueError):
    """A safe, body-free refusal suitable for machine-readable output."""

    def __init__(self, code: str, *, surface: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.surface = surface


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
            self.surface,
            self.expected_version,
            "message_stopped",
        )

    @property
    def route(self) -> str:
        if self.wake_route:
            return self.wake_route
        return "direct" if self.wake_supported else "none"

    @property
    def acceptance_key(self) -> str:
        suffix = "" if self.acceptance_role == "surface" else ":broker"
        return f"{self.surface}{suffix}"


@dataclass(frozen=True)
class AcceptanceMatrix:
    project: str
    cells: tuple[AcceptanceCell, ...]


def validate_run_id(value: str) -> str:
    run_id = str(value or "").strip()
    if not _RUN_ID.fullmatch(run_id):
        raise AcceptanceContractError("run_id_invalid")
    return run_id


def validate_deployed_release(release_sha: str, server_build: str) -> tuple[str, str]:
    expected = str(release_sha or "").strip()
    observed = str(server_build or "").strip()
    if not _RELEASE_SHA.fullmatch(expected):
        raise AcceptanceContractError("release_sha_invalid")
    if not _SERVER_BUILD.fullmatch(observed):
        raise AcceptanceContractError("server_build_unresolved")
    if expected != observed:
        raise AcceptanceContractError("deployed_release_mismatch")
    return expected, observed


def require_text(value: Any, *, code: str, surface: str | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcceptanceContractError(code, surface=surface)
    return value.strip()


def _optional_text(value: Any, *, code: str, surface: str) -> str | None:
    if value is None:
        return None
    return require_text(value, code=code, surface=surface)


def _cell(raw: Any, *, evidence_required: bool) -> AcceptanceCell:
    if not isinstance(raw, dict) or set(raw) - _CELL_KEYS:
        raise AcceptanceContractError("cell_shape_invalid")
    surface = require_text(raw.get("surface"), code="surface_missing")
    if surface not in ACCEPTANCE_SURFACES:
        raise AcceptanceContractError("surface_unsupported", surface=surface)
    version = require_text(
        raw.get("expected_version"),
        code="expected_version_missing",
        surface=surface,
    )
    if evidence_required and not _version_acceptance_supported(surface, version):
        raise AcceptanceContractError("expected_version_unproven", surface=surface)
    mode = require_text(raw.get("mode"), code="mode_missing", surface=surface)
    if mode not in {"create", "identify"}:
        raise AcceptanceContractError("mode_invalid", surface=surface)
    if mode == "create" and (
        surface in _IDENTIFY_ONLY_SURFACES
        or not surface_operation_supported(surface, version, "create")
    ):
        raise AcceptanceContractError("create_unproven", surface=surface)
    session_id = _optional_text(
        raw.get("session_id"), code="session_id_invalid", surface=surface
    )
    if mode == "identify" and session_id is None:
        raise AcceptanceContractError("session_id_missing", surface=surface)
    if mode == "create" and session_id is not None:
        raise AcceptanceContractError("session_id_forbidden", surface=surface)
    machine_id = _optional_text(
        raw.get("machine_id"), code="machine_id_invalid", surface=surface
    )
    broker_session_id = _optional_text(
        raw.get("broker_session_id"),
        code="broker_session_id_invalid",
        surface=surface,
    )
    role = require_text(
        raw.get("acceptance_role"),
        code="acceptance_role_missing",
        surface=surface,
    )
    if role not in _ACCEPTANCE_ROLES:
        raise AcceptanceContractError("acceptance_role_invalid", surface=surface)
    wake_route = require_text(
        raw.get("wake_route"), code="wake_route_missing", surface=surface
    )
    if wake_route not in _WAKE_ROUTES:
        raise AcceptanceContractError("wake_route_invalid", surface=surface)
    if role == "surface":
        expected_route = "none" if surface in _IDENTIFY_ONLY_SURFACES else "direct"
        if wake_route != expected_route:
            raise AcceptanceContractError("surface_wake_route_invalid", surface=surface)
        if broker_session_id is not None:
            raise AcceptanceContractError(
                "broker_session_id_forbidden", surface=surface
            )
    else:
        if wake_route != "broker":
            raise AcceptanceContractError("broker_wake_route_required", surface=surface)
        if mode != "identify":
            raise AcceptanceContractError("broker_identify_required", surface=surface)
        if surface in _IDENTIFY_ONLY_SURFACES:
            raise AcceptanceContractError("broker_surface_unproven", surface=surface)
        if machine_id is None:
            raise AcceptanceContractError("broker_machine_required", surface=surface)
        if broker_session_id is None:
            raise AcceptanceContractError("broker_session_required", surface=surface)
        if broker_session_id == session_id:
            raise AcceptanceContractError("broker_target_same_session", surface=surface)
    return AcceptanceCell(
        surface=surface,
        expected_version=version,
        mode=mode,
        session_id=session_id,
        machine_id=machine_id,
        model=_optional_text(raw.get("model"), code="model_invalid", surface=surface),
        acceptance_role=role,
        wake_route=wake_route,
        broker_session_id=broker_session_id,
    )


def _parse_matrix(
    raw: Any, *, evidence_required: bool, complete_required: bool
) -> AcceptanceMatrix:
    if not isinstance(raw, dict) or set(raw) - _MATRIX_KEYS:
        raise AcceptanceContractError("matrix_shape_invalid")
    if raw.get("schema") != SCHEMA_VERSION:
        raise AcceptanceContractError("matrix_schema_invalid")
    project = require_text(raw.get("project"), code="project_missing")
    raw_cells = raw.get("cells")
    if not isinstance(raw_cells, list):
        raise AcceptanceContractError("cells_invalid")
    cells = tuple(
        _cell(value, evidence_required=evidence_required) for value in raw_cells
    )
    if not complete_required:
        if not cells:
            raise AcceptanceContractError("candidate_cells_empty")
        keys = tuple(cell.acceptance_key for cell in cells)
        if len(keys) != len(set(keys)):
            raise AcceptanceContractError("candidate_cell_duplicate")
        for cell in cells:
            operation = acceptance_operation(cell.surface)
            capability = capability_for_surface(cell.surface)
            interface = getattr(capability, operation, "none")
            if not surface_version_supported(cell.surface, cell.expected_version):
                raise AcceptanceContractError(
                    "candidate_version_unsupported", surface=cell.surface
                )
            if interface != "private":
                raise AcceptanceContractError(
                    "candidate_route_not_private", surface=cell.surface
                )
            if surface_operation_supported(
                cell.surface, cell.expected_version, operation
            ):
                raise AcceptanceContractError(
                    "candidate_version_already_proven", surface=cell.surface
                )
        ordered = tuple(
            sorted(
                cells,
                key=lambda cell: (
                    ACCEPTANCE_SURFACES.index(cell.surface),
                    0 if cell.acceptance_role == "surface" else 1,
                ),
            )
        )
        return AcceptanceMatrix(project=project, cells=ordered)
    surface_cells = tuple(cell for cell in cells if cell.acceptance_role == "surface")
    surfaces = tuple(cell.surface for cell in surface_cells)
    if len(surfaces) != len(set(surfaces)):
        raise AcceptanceContractError("surface_duplicate")
    if set(surfaces) != set(ACCEPTANCE_SURFACES):
        raise AcceptanceContractError("surface_matrix_incomplete")
    broker_cells = tuple(cell for cell in cells if cell.acceptance_role == "broker")
    if len(broker_cells) != 1:
        raise AcceptanceContractError("broker_cell_count_invalid")
    ordered_surfaces = tuple(
        sorted(surface_cells, key=lambda cell: ACCEPTANCE_SURFACES.index(cell.surface))
    )
    ordered = (*ordered_surfaces, broker_cells[0])
    return AcceptanceMatrix(project=project, cells=ordered)


def parse_matrix(raw: Any) -> AcceptanceMatrix:
    return _parse_matrix(raw, evidence_required=True, complete_required=True)


def parse_candidate_matrix(raw: Any) -> AcceptanceMatrix:
    """Validate a nonempty subset of exact unproven private-route cells."""
    return _parse_matrix(raw, evidence_required=False, complete_required=False)


def parse_readiness_matrix(raw: Any) -> AcceptanceMatrix:
    """Validate the full matrix while deferring exact private-version proof."""
    return _parse_matrix(raw, evidence_required=False, complete_required=True)


def _read_matrix(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceContractError("matrix_unreadable") from exc


def load_matrix(path: Path) -> AcceptanceMatrix:
    return parse_matrix(_read_matrix(path))


def load_candidate_matrix(path: Path) -> AcceptanceMatrix:
    return parse_candidate_matrix(_read_matrix(path))


def load_readiness_matrix(path: Path) -> AcceptanceMatrix:
    return parse_readiness_matrix(_read_matrix(path))


__all__ = [
    "ACCEPTANCE_SURFACES",
    "AcceptanceCell",
    "AcceptanceContractError",
    "AcceptanceMatrix",
    "acceptance_operation",
    "load_candidate_matrix",
    "load_matrix",
    "load_readiness_matrix",
    "parse_candidate_matrix",
    "parse_matrix",
    "parse_readiness_matrix",
    "require_text",
    "validate_deployed_release",
    "validate_run_id",
]
