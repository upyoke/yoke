"""Secure command adapter for production Fleet live acceptance."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from typing import Annotated, Any, Iterator, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from runtime.api.tools.session_control_live_acceptance import main as acceptance_main
from runtime.api.tools.session_control_live_acceptance_contract import (
    ACCEPTANCE_SURFACES,
    SCHEMA_VERSION,
    AcceptanceContractError,
    acceptance_operation,
    parse_candidate_matrix,
    parse_matrix,
    validate_deployed_release,
    validate_run_id,
)
from runtime.api.tools.session_control_live_acceptance_wake_route import (
    expected_wake_route,
)
from yoke_contracts.session_execution import is_subagent_execution
from yoke_contracts.session_control.surface_versions import surface_operation_supported
from yoke_cli.config.machine_config_file import (
    MachineConfigFileError,
    atomic_write_text,
    ensure_owner_only_directory,
)
from yoke_core.domain.deploy_product_source import (
    DeployProductSourceError,
    validate_product_source,
)
from yoke_core.domain.project_scratch_dir import (
    ScratchRootResolutionError,
    ephemeral_payload,
    scratch_root,
)


BROKER_ACCEPTANCE_SURFACE = "codex-cli"
MAX_BINDINGS_CHARACTERS = 16 * 1024
_REPORT_KIND = "fleet_session_control_live_acceptance"
_NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=256),
]
_SurfaceVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=128),
]


class _AcceptanceVersions(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_by_alias=True, validate_by_name=False
    )

    claude_cli: _SurfaceVersion = Field(alias="claude-cli")
    claude_desktop: _SurfaceVersion = Field(alias="claude-desktop")
    codex_cli: _SurfaceVersion = Field(alias="codex-cli")
    codex_desktop: _SurfaceVersion = Field(alias="codex-desktop")
    cursor_cli: _SurfaceVersion = Field(alias="cursor-cli")


class BrokerAcceptanceBinding(BaseModel):
    """Exact stopped target and same-machine peer used for broker proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_session_id: _NonEmptyText
    machine_id: _NonEmptyText
    peer_session_id: _NonEmptyText


class LiveAcceptanceBindings(BaseModel):
    """Operator-supplied identities and observed versions; no route controls."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_by_alias=True, validate_by_name=False
    )

    schema_version: Literal[1] = Field(alias="schema")
    versions: _AcceptanceVersions
    claude_desktop_session_id: _NonEmptyText
    broker: BrokerAcceptanceBinding


def _canonical_document(
    project: str,
    raw_cells: list[dict[str, Any]],
    *,
    qualification_candidate: bool = False,
) -> dict[str, Any]:
    if qualification_candidate:
        raw_cells = [
            cell
            for cell in raw_cells
            if not surface_operation_supported(
                cell["surface"],
                cell["expected_version"],
                acceptance_operation(cell["surface"]),
            )
        ]
    parser = parse_candidate_matrix if qualification_candidate else parse_matrix
    parsed = parser({"schema": SCHEMA_VERSION, "project": project, "cells": raw_cells})
    cells: list[dict[str, Any]] = []
    for cell in parsed.cells:
        row: dict[str, Any] = {
            "surface": cell.surface,
            "expected_version": cell.expected_version,
            "mode": cell.mode,
            "acceptance_role": cell.acceptance_role,
            "wake_route": cell.route,
        }
        for key in ("session_id", "machine_id", "model", "broker_session_id"):
            value = getattr(cell, key)
            if value is not None:
                row[key] = value
        cells.append(row)
    return {"schema": SCHEMA_VERSION, "project": parsed.project, "cells": cells}


def build_acceptance_matrix_document(
    project: str,
    bindings: LiveAcceptanceBindings,
    *,
    qualification_candidate: bool = False,
) -> dict[str, Any]:
    """Build the only supported five-surface plus one-broker matrix."""
    versions = bindings.versions.model_dump(by_alias=True)
    cells: list[dict[str, Any]] = []
    for surface in ACCEPTANCE_SURFACES:
        active_only = surface == "claude-desktop"
        row: dict[str, Any] = {
            "surface": surface,
            "expected_version": versions[surface],
            "mode": "identify" if active_only else "create",
            "acceptance_role": "surface",
            "wake_route": expected_wake_route(surface, versions[surface], versions),
        }
        if active_only:
            row["session_id"] = bindings.claude_desktop_session_id
        cells.append(row)
    cells.append(
        {
            "surface": BROKER_ACCEPTANCE_SURFACE,
            "expected_version": versions[BROKER_ACCEPTANCE_SURFACE],
            "mode": "identify",
            "session_id": bindings.broker.target_session_id,
            "machine_id": bindings.broker.machine_id,
            "acceptance_role": "broker",
            "wake_route": "broker",
            "broker_session_id": bindings.broker.peer_session_id,
        }
    )
    return _canonical_document(
        project,
        cells,
        qualification_candidate=qualification_candidate,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yoke session-control acceptance run",
        description=(
            "Run or preview production Fleet acceptance or stage candidate "
            "qualification."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--bindings-stdin", action="store_true", required=True)
    parser.add_argument("--qualification-candidate", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--poll-seconds", type=float)
    parser.add_argument("--unsupported-observation-seconds", type=float)
    return parser


def _validate_windows(args: argparse.Namespace) -> None:
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        raise AcceptanceContractError("poll_window_invalid")
    if args.poll_seconds is not None and args.poll_seconds <= 0:
        raise AcceptanceContractError("poll_window_invalid")
    if (
        args.unsupported_observation_seconds is not None
        and args.unsupported_observation_seconds < 0
    ):
        raise AcceptanceContractError("observation_window_invalid")


def _validate_source(release_sha: str) -> None:
    validate_deployed_release(release_sha, release_sha)
    try:
        source = validate_product_source(Path.cwd(), release_sha)
    except DeployProductSourceError as exc:
        raise AcceptanceContractError("acceptance_source_release_unverified") from exc
    if source.commit != release_sha:
        raise AcceptanceContractError("acceptance_source_release_unverified")


def _read_bindings() -> LiveAcceptanceBindings:
    try:
        raw = sys.stdin.read(MAX_BINDINGS_CHARACTERS + 1)
    except Exception as exc:
        raise AcceptanceContractError("bindings_unreadable") from exc
    if len(raw) > MAX_BINDINGS_CHARACTERS:
        raise AcceptanceContractError("bindings_too_large")
    try:
        return LiveAcceptanceBindings.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise AcceptanceContractError("bindings_invalid") from exc


@contextmanager
def _matrix_file(project: str, document: dict[str, Any]) -> Iterator[Path]:
    try:
        ensure_owner_only_directory(scratch_root(project) / "payloads")
        with ephemeral_payload(
            "fleet-acceptance-matrix", suffix=".json", project=project
        ) as target:
            atomic_write_text(
                target,
                json.dumps(document, sort_keys=True, separators=(",", ":")),
            )
            yield target
    except (MachineConfigFileError, ScratchRootResolutionError, OSError) as exc:
        raise AcceptanceContractError("acceptance_scratch_unavailable") from exc


def _refusal(exc: AcceptanceContractError) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": 1,
        "kind": _REPORT_KIND,
        "status": "refused",
        "failure_code": exc.code,
    }
    if exc.surface:
        report["surface"] = exc.surface
    return report


def _acceptance_argv(args: argparse.Namespace, matrix_path: Path) -> list[str]:
    forwarded = [
        "--matrix",
        str(matrix_path),
        "--run-id",
        args.run_id,
        "--release-sha",
        args.release_sha,
    ]
    if args.qualification_candidate:
        forwarded.append("--qualification-candidate")
    for flag, value in (
        ("--timeout-seconds", args.timeout_seconds),
        ("--poll-seconds", args.poll_seconds),
        ("--unsupported-observation-seconds", args.unsupported_observation_seconds),
    ):
        if value is not None:
            forwarded.extend((flag, str(value)))
    return forwarded


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if is_subagent_execution():
            raise AcceptanceContractError("top_level_session_required")
        validate_run_id(args.run_id)
        _validate_windows(args)
        _validate_source(args.release_sha)
        bindings = _read_bindings()
        document = build_acceptance_matrix_document(
            args.project,
            bindings,
            qualification_candidate=args.qualification_candidate,
        )
        if args.preview:
            print(
                json.dumps(
                    {
                        "schema": 1,
                        "kind": "fleet_session_control_live_acceptance_preview",
                        "status": "ready",
                        "run_id": args.run_id,
                        "release_sha": args.release_sha,
                        "project": document["project"],
                        "cells": document["cells"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        with _matrix_file(args.project, document) as matrix_path:
            return int(acceptance_main(_acceptance_argv(args, matrix_path)))
    except AcceptanceContractError as exc:
        report = _refusal(exc)
    except Exception:
        report = _refusal(AcceptanceContractError("internal_error"))
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 2


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "BROKER_ACCEPTANCE_SURFACE",
    "MAX_BINDINGS_CHARACTERS",
    "BrokerAcceptanceBinding",
    "LiveAcceptanceBindings",
    "build_acceptance_matrix_document",
    "main",
]
