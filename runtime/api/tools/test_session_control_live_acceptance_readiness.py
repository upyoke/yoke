"""Fail-closed private-route readiness report tests."""

from __future__ import annotations

import json

from runtime.api.tools import session_control_live_acceptance_readiness as readiness
from runtime.api.tools.session_control_live_acceptance_contract import (
    SCHEMA_VERSION,
    ACCEPTANCE_SURFACES,
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
    "codex-desktop": "26.818.31338",
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
                "mode": "identify" if surface == "claude-desktop" else "create",
                "acceptance_role": "surface",
                "wake_route": "direct",
                **(
                    {"session_id": "active-claude-desktop"}
                    if surface == "claude-desktop"
                    else {}
                ),
            }
            for surface in ACCEPTANCE_SURFACES
        ]
        + [
            {
                "surface": "codex-cli",
                "expected_version": versions["codex-cli"],
                "mode": "identify",
                "session_id": "broker-target-session",
                "machine_id": "machine-1",
                "acceptance_role": "broker",
                "wake_route": MACHINE_SELECTED_ROUTE,
                "broker_session_id": "broker-peer-session",
            }
        ],
    }


def test_current_claude_versions_are_qualified_by_registered_policies() -> None:
    report = readiness.readiness_report(
        parse_readiness_matrix(_matrix(CURRENT_VERSIONS))
    )
    cells = {cell["surface"]: cell for cell in report["cells"]}

    assert report["status"] == "ready"
    assert cells["claude-desktop"] == {
        "surface": "claude-desktop",
        "expected_version": "1.34493.1",
        "operation": "message_active",
        "status": "qualified",
    }
    assert all(cell["status"] == "qualified" for cell in cells.values())


def test_exact_policy_names_missing_evidence_and_candidate_action(monkeypatch) -> None:
    require_exact_desktop_active_policy(monkeypatch)
    report = readiness.readiness_report(
        parse_readiness_matrix(_matrix(CURRENT_VERSIONS))
    )
    cells = {cell["surface"]: cell for cell in report["cells"]}

    assert report["status"] == "blocked"
    assert cells["claude-desktop"] == {
        "surface": "claude-desktop",
        "expected_version": "1.34493.1",
        "operation": "message_active",
        "status": "blocked",
        "failure_code": "private_route_evidence_missing",
        "evidence_source": readiness.EVIDENCE_SOURCE,
        "interface": "private",
        "required_live_proof": [
            "matching_registration_identity",
            "model_visible_hook_retrieval",
            "explicit_acknowledgement",
            "idempotent_receipt_deduplication",
        ],
        "operator_action": {
            "action": "open_and_identify_exact_qualified_version",
            "exact_version": "1.32885.1",
            "then": "rerun_private_route_readiness",
        },
        "candidate_qualification_action": {
            "action": "capture_version_specific_live_acceptance",
            "exact_version": "1.34493.1",
            "then": "add_as_separately_qualified_private_route",
        },
    }
    assert cells["claude-cli"] == {
        "surface": "claude-cli",
        "expected_version": "2.1.241",
        "operation": "message_stopped",
        "status": "qualified",
    }
    assert all(
        cells[surface]["status"] == "qualified" for surface in ACCEPTANCE_SURFACES[2:]
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
