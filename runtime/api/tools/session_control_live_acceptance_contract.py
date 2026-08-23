"""Closed input contract for deployed Fleet session-control acceptance."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from yoke_contracts.session_control.surface_versions import surface_operation_supported


SCHEMA_VERSION = 1
ACCEPTANCE_SURFACES = (
    "claude-cli",
    "claude-desktop",
    "codex-cli",
    "codex-desktop",
    "cursor-cli",
)
_CREATE_UNSUPPORTED = frozenset({"claude-desktop"})
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_RELEASE_SHA = re.compile(r"^[0-9a-f]{40}$")
_SERVER_BUILD = re.compile(r"^[0-9a-f]{7,40}$")
_MATRIX_KEYS = frozenset({"schema", "project", "cells"})
_CELL_KEYS = frozenset(
    {"surface", "expected_version", "mode", "session_id", "machine_id", "model"}
)


def _version_acceptance_supported(surface: str, version: str) -> bool:
    operation = "message_active" if surface == "claude-desktop" else "message_stopped"
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

    @property
    def wake_supported(self) -> bool:
        return surface_operation_supported(
            self.surface,
            self.expected_version,
            "message_stopped",
        )


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
    if not expected.startswith(observed):
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


def _cell(raw: Any) -> AcceptanceCell:
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
    if not _version_acceptance_supported(surface, version):
        raise AcceptanceContractError("expected_version_unproven", surface=surface)
    mode = require_text(raw.get("mode"), code="mode_missing", surface=surface)
    if mode not in {"create", "identify"}:
        raise AcceptanceContractError("mode_invalid", surface=surface)
    if mode == "create" and (
        surface in _CREATE_UNSUPPORTED
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
    return AcceptanceCell(
        surface=surface,
        expected_version=version,
        mode=mode,
        session_id=session_id,
        machine_id=_optional_text(
            raw.get("machine_id"), code="machine_id_invalid", surface=surface
        ),
        model=_optional_text(raw.get("model"), code="model_invalid", surface=surface),
    )


def parse_matrix(raw: Any) -> AcceptanceMatrix:
    if not isinstance(raw, dict) or set(raw) - _MATRIX_KEYS:
        raise AcceptanceContractError("matrix_shape_invalid")
    if raw.get("schema") != SCHEMA_VERSION:
        raise AcceptanceContractError("matrix_schema_invalid")
    project = require_text(raw.get("project"), code="project_missing")
    raw_cells = raw.get("cells")
    if not isinstance(raw_cells, list):
        raise AcceptanceContractError("cells_invalid")
    cells = tuple(_cell(value) for value in raw_cells)
    surfaces = tuple(cell.surface for cell in cells)
    if len(surfaces) != len(set(surfaces)):
        raise AcceptanceContractError("surface_duplicate")
    if set(surfaces) != set(ACCEPTANCE_SURFACES):
        raise AcceptanceContractError("surface_matrix_incomplete")
    ordered = tuple(
        sorted(cells, key=lambda cell: ACCEPTANCE_SURFACES.index(cell.surface))
    )
    return AcceptanceMatrix(project=project, cells=ordered)


def load_matrix(path: Path) -> AcceptanceMatrix:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcceptanceContractError("matrix_unreadable") from exc
    return parse_matrix(raw)


__all__ = [
    "ACCEPTANCE_SURFACES",
    "AcceptanceCell",
    "AcceptanceContractError",
    "AcceptanceMatrix",
    "load_matrix",
    "parse_matrix",
    "require_text",
    "validate_deployed_release",
    "validate_run_id",
]
