"""Body-free report builders for Fleet live acceptance."""

from __future__ import annotations

from typing import Any

from runtime.api.tools.session_control_live_acceptance_contract import AcceptanceCell


FAILED_STATUS = "failed"


def _cell_identity(cell: AcceptanceCell) -> dict[str, Any]:
    return {
        "surface": cell.surface,
        "expected_version": cell.expected_version,
        "mode": cell.mode,
        "acceptance_role": cell.acceptance_role,
        "wake_route": cell.route,
    }


def failed_cell_report(
    cell: AcceptanceCell,
    *,
    failure_code: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        **_cell_identity(cell),
        "status": FAILED_STATUS,
        "failure_code": failure_code,
    }
    if evidence is not None:
        report["failure_evidence"] = evidence
    return report


def _observed_cell(
    cell: AcceptanceCell,
    *,
    session_id: str,
    baseline: dict[str, Any],
    initial: dict[str, Any],
    initial_deduplicated: bool,
    waiting: dict[str, Any],
) -> dict[str, Any]:
    return {
        **_cell_identity(cell),
        "observed_version": waiting["executor_version"],
        "session_id": session_id,
        "registration_identity_matched": True,
        "baseline_liveness": baseline["liveness"],
        "initial_message": initial,
        "initial_deduplicated": initial_deduplicated,
        "stopped_liveness": waiting["liveness"],
        "stopped_session_mode": waiting["mode"],
        "turn_posture": waiting["turn_posture"],
        "wake_supported": cell.route != "none",
    }


def _with_launch(
    report: dict[str, Any], launch: dict[str, Any] | None
) -> dict[str, Any]:
    if launch is not None:
        report["launch_id"] = launch["launch_id"]
    return report


def deferred_cell_report(
    cell: AcceptanceCell,
    *,
    session_id: str,
    baseline: dict[str, Any],
    initial: dict[str, Any],
    initial_deduplicated: bool,
    waiting: dict[str, Any],
    launch: dict[str, Any] | None,
) -> dict[str, Any]:
    report = _observed_cell(
        cell,
        session_id=session_id,
        baseline=baseline,
        initial=initial,
        initial_deduplicated=initial_deduplicated,
        waiting=waiting,
    )
    report.update(
        {
            "status": "deferred",
            "deferral_code": "desktop_single_writer_lock",
            "wake_outcome": "deferred_environment",
        }
    )
    return _with_launch(report, launch)


def passed_cell_report(
    cell: AcceptanceCell,
    *,
    session_id: str,
    baseline: dict[str, Any],
    initial: dict[str, Any],
    initial_deduplicated: bool,
    waiting: dict[str, Any],
    wake: dict[str, Any],
    wake_outcome: str,
    wake_deduplicated: bool,
    launch: dict[str, Any] | None,
    route_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = _observed_cell(
        cell,
        session_id=session_id,
        baseline=baseline,
        initial=initial,
        initial_deduplicated=initial_deduplicated,
        waiting=waiting,
    )
    report.update(
        {
            "status": "passed",
            "wake_outcome": wake_outcome,
            "wake_message": wake,
            "wake_deduplicated": wake_deduplicated,
        }
    )
    if route_selection is not None:
        report["route_selection"] = route_selection
    return _with_launch(report, launch)


__all__ = [
    "FAILED_STATUS",
    "deferred_cell_report",
    "failed_cell_report",
    "passed_cell_report",
]
