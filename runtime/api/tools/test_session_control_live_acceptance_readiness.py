"""Fail-closed private-route readiness report tests."""

from __future__ import annotations

import json

from runtime.api.tools import session_control_live_acceptance_readiness as readiness
from runtime.api.tools.session_control_live_acceptance_contract import (
    SCHEMA_VERSION,
    ACCEPTANCE_SURFACE_CELLS,
    parse_readiness_matrix,
)
from runtime.api.tools.session_control_live_acceptance_wake_route import (
    MACHINE_SELECTED_ROUTE,
)
from runtime.api.tools.test_session_control_live_acceptance_policy_support import (
    require_exact_desktop_active_policy,
)


QUALIFIED_VERSIONS = {
    "claude-cli": "2.1.238",
    "claude-desktop": "1.32885.1",
    "codex-cli": "0.149.0-alpha.4.3",
    "cursor-cli": "2026.08.11-e8db854",
}
CURRENT_VERSIONS = {
    **QUALIFIED_VERSIONS,
    "claude-cli": "2.1.241",
    "claude-desktop": "1.34493.1",
}


def _matrix(versions: dict[str, str]) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "project": "yoke",
        "cells": [
            {
                "surface": surface,
                "expected_version": versions[surface],
                "mode": mode,
                "acceptance_role": "surface",
                "proof_scope": "registered_session_control_surface",
                # A desktop surface has no wake route however the machine is
                # equipped: its own operator is the only thing that resumes it.
                "wake_route": "none" if surface == "claude-desktop" else "direct",
                **(
                    {"session_id": "active-claude-desktop"}
                    if mode == "identify"
                    else {}
                ),
            }
            for surface, mode in ACCEPTANCE_SURFACE_CELLS
        ]
        + [
            {
                "surface": "codex-cli",
                "expected_version": versions["codex-cli"],
                "mode": "identify",
                "session_id": "broker-target-session",
                "machine_id": "machine-1",
                "acceptance_role": "broker",
                "proof_scope": "registered_broker_wake_route",
                "wake_route": MACHINE_SELECTED_ROUTE,
                "broker_session_id": "broker-peer-session",
            }
        ],
    }


def test_current_claude_versions_are_qualified_by_registered_policies() -> None:
    report = readiness.readiness_report(
        parse_readiness_matrix(_matrix(CURRENT_VERSIONS))
    )
    cells = {cell["cell_name"]: cell for cell in report["cells"]}
    desktop = cells["claude-desktop:registered_session_control_surface:identify"]

    assert report["status"] == "ready"
    assert desktop["operation"] == "message_active"
    assert desktop["operator_visible_desktop_occupancy_proven"] is False
    assert all(cell["status"] == "qualified" for cell in cells.values())


def test_exact_policy_names_missing_evidence_and_candidate_action(monkeypatch) -> None:
    require_exact_desktop_active_policy(monkeypatch)
    report = readiness.readiness_report(
        parse_readiness_matrix(_matrix(CURRENT_VERSIONS))
    )
    cells = {cell["cell_name"]: cell for cell in report["cells"]}
    desktop = cells["claude-desktop:registered_session_control_surface:identify"]

    assert report["status"] == "blocked"
    assert desktop["failure_code"] == "private_route_evidence_missing"
    assert desktop["operator_action"]["exact_version"] == "1.32885.1"
    assert desktop["candidate_qualification_action"]["exact_version"] == "1.34493.1"
    assert (
        cells["claude-cli:registered_session_control_surface:create"]["status"]
        == "qualified"
    )
    assert all(
        cell["status"] == "qualified" for cell in cells.values() if cell is not desktop
    )


def test_registered_minimum_versions_remain_qualified() -> None:
    report = readiness.readiness_report(
        parse_readiness_matrix(_matrix(QUALIFIED_VERSIONS))
    )

    assert report["status"] == "ready"
    assert all(cell["status"] == "qualified" for cell in report["cells"])


def test_cli_report_is_non_mutating_machine_readable(tmp_path, capsys) -> None:
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(json.dumps(_matrix(CURRENT_VERSIONS)), encoding="utf-8")

    code = readiness.main(["--matrix", str(matrix_path)])

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["status"] == "ready"
    assert report["kind"] == "fleet_session_control_private_route_readiness"


def test_refusal_never_reflects_unknown_matrix_fields(tmp_path, capsys) -> None:
    matrix = _matrix(CURRENT_VERSIONS)
    matrix["body"] = "MUST-NOT-REFLECT"
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")

    code = readiness.main(["--matrix", str(matrix_path)])

    output = capsys.readouterr().out
    assert code == 2
    assert "MUST-NOT-REFLECT" not in output
    assert json.loads(output)["failure_code"] == "matrix_shape_invalid"
