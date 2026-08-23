"""Non-mutating qualification report for Fleet live-acceptance matrices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    AcceptanceMatrix,
    acceptance_operation,
    load_readiness_matrix,
)
from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)


EVIDENCE_SOURCE = "yoke_contracts.session_control.SESSION_SURFACE_CAPABILITIES"
_PROOF_REQUIREMENTS = {
    "message_active": (
        "matching_registration_identity",
        "model_visible_hook_retrieval",
        "explicit_acknowledgement",
        "idempotent_receipt_deduplication",
    ),
    "message_stopped": (
        "matching_registration_identity",
        "model_visible_hook_retrieval",
        "explicit_acknowledgement",
        "waiting_posture",
        "native_wake_attempt",
        "idempotent_receipt_deduplication",
    ),
}


def _operator_action(cell: AcceptanceCell, exact_version: str) -> dict[str, str]:
    action = (
        "open_and_identify_exact_qualified_version"
        if cell.mode == "identify"
        else "install_and_register_exact_qualified_version"
    )
    return {
        "action": action,
        "exact_version": exact_version,
        "then": "rerun_private_route_readiness",
    }


def _cell_report(cell: AcceptanceCell) -> dict[str, Any]:
    operation = acceptance_operation(cell.surface)
    report: dict[str, Any] = {
        "surface": cell.surface,
        "expected_version": cell.expected_version,
        "operation": operation,
    }
    if surface_operation_supported(cell.surface, cell.expected_version, operation):
        report["status"] = "qualified"
        return report
    capability = capability_for_surface(cell.surface)
    interface = getattr(capability, operation) if capability else "none"
    report.update(
        status="blocked",
        failure_code=(
            "private_route_evidence_missing"
            if interface == "private"
            else "route_evidence_missing"
        ),
        evidence_source=EVIDENCE_SOURCE,
        interface=interface,
        required_live_proof=list(_PROOF_REQUIREMENTS[operation]),
    )
    if capability is not None and interface == "private":
        report["operator_action"] = _operator_action(cell, capability.minimum_version)
        report["candidate_qualification_action"] = {
            "action": "capture_version_specific_live_acceptance",
            "exact_version": cell.expected_version,
            "then": "add_as_separately_qualified_private_route",
        }
    return report


def readiness_report(matrix: AcceptanceMatrix) -> dict[str, Any]:
    cells = [
        _cell_report(cell) for cell in matrix.cells if cell.acceptance_role == "surface"
    ]
    ready = all(cell["status"] == "qualified" for cell in cells)
    return {
        "schema": 1,
        "kind": "fleet_session_control_private_route_readiness",
        "project": matrix.project,
        "status": "ready" if ready else "blocked",
        "cells": cells,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check exact private-route version evidence without contacting Yoke, "
            "launching a session, or sending a message."
        )
    )
    parser.add_argument("--matrix", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = readiness_report(load_readiness_matrix(args.matrix))
        code = 0 if report["status"] == "ready" else 1
    except AcceptanceContractError as exc:
        report = {
            "schema": 1,
            "kind": "fleet_session_control_private_route_readiness",
            "status": "refused",
            "failure_code": exc.code,
        }
        if exc.surface:
            report["surface"] = exc.surface
        code = 2
    except Exception:
        report = {
            "schema": 1,
            "kind": "fleet_session_control_private_route_readiness",
            "status": "refused",
            "failure_code": "internal_error",
        }
        code = 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
