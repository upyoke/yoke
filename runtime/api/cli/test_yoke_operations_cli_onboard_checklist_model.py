from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.config.onboard_checklist_schema import (
    CHECKLIST_LAYERS,
    CHECKLIST_STATUSES,
)


def test_onboard_checklist_model_renders_deterministic_json(
    tmp_path: Path,
) -> None:
    from yoke_cli.config import onboard_checklist as checklist

    assert checklist.CHECKLIST_STATUSES == CHECKLIST_STATUSES
    assert checklist.CHECKLIST_LAYERS == CHECKLIST_LAYERS

    machine_config = tmp_path / ".yoke" / "config.json"
    checkout = tmp_path / "checkout"
    run = checklist.ChecklistRun(
        machine_config_path=machine_config,
        checkout_path=checkout,
        project_id=7,
        rows=[
            checklist.ChecklistRow(
                id="machine-config",
                layer="machine",
                title="Machine config",
                status="needed",
                hint="Run yoke onboard --yes before project setup.",
                details=("Stores API URL and a token-file reference.",),
            ),
            checklist.ChecklistRow(
                id="project-contract",
                layer="project",
                title="Project contract files",
                status="configured",
                evidence={"paths": [".yoke/lint-config"]},
            ),
            checklist.ChecklistRow(
                id="handoff",
                layer="agentic",
                title="/yoke onboard-project handoff",
                status="deferred",
            ),
        ],
    )

    first = checklist.dumps_json(run)
    second = checklist.dumps_json(run)

    assert first == second
    assert first.endswith("\n")
    payload = json.loads(first)
    assert payload["operation"] == "onboard.checklist"
    assert payload["machine_config_path"] == str(machine_config)
    assert payload["checkout_path"] == str(checkout)
    assert payload["project_id"] == 7
    assert payload["rows"][0]["details"] == [
        "Stores API URL and a token-file reference."
    ]


def test_onboard_checklist_status_transitions_reject_unknown_statuses() -> None:
    from yoke_cli.config import onboard_checklist as checklist

    row = checklist.ChecklistRow(
        id="machine-config",
        layer="machine",
        title="Machine config",
        status="unknown",
    )

    configured = checklist.transition_status(
        row,
        "configured",
        evidence={"config_path": "~/.yoke/config.json"},
    )

    assert configured.status == "configured"
    assert configured.evidence == {"config_path": "~/.yoke/config.json"}
    assert row.status == "unknown"
    with pytest.raises(checklist.ChecklistValidationError):
        checklist.transition_status(row, "done")
    with pytest.raises(checklist.ChecklistValidationError):
        checklist.ChecklistRow(
            id="bad-status",
            layer="machine",
            title="Bad status",
            status="waiting",
        )


def test_onboard_checklist_project_view_redacts_raw_secrets(
    tmp_path: Path,
) -> None:
    from yoke_cli.config import onboard_checklist as checklist

    raw_secret = "super-secret-token"
    run = checklist.ChecklistRun(
        machine_config_path=tmp_path / ".yoke" / "config.json",
        checkout_path=tmp_path / "checkout",
        project_id=7,
        rows=[
            checklist.ChecklistRow(
                id="machine-token",
                layer="machine",
                title="Machine token",
                status="verified",
                evidence={
                    "token_file": str(tmp_path / ".yoke" / "secrets" / "prod.token"),
                    "token": raw_secret,
                },
            ),
            checklist.ChecklistRow(
                id="project-contract",
                layer="project",
                title="Project contract files",
                status="needed",
                hint="Render project-local policy files.",
            ),
        ],
    )

    rendered = checklist.render_project_view(run)

    assert "Machine token" in rendered
    assert "verified" in rendered
    assert "Project contract files" in rendered
    assert raw_secret not in rendered
    assert "[redacted]" in rendered


def test_onboard_checklist_handoff_json_summarizes_rows(
    tmp_path: Path,
) -> None:
    from yoke_cli.config import onboard_checklist as checklist

    machine_config = tmp_path / ".yoke" / "config.json"
    checkout = tmp_path / "checkout"
    run = checklist.ChecklistRun(
        machine_config_path=machine_config,
        checkout_path=checkout,
        project_id=7,
        rows=[
            checklist.ChecklistRow(
                id="machine-config",
                layer="machine",
                title="Machine config",
                status="verified",
                evidence={"config_path": str(machine_config)},
            ),
            checklist.ChecklistRow(
                id="capability-github",
                layer="capability",
                title="GitHub capability",
                status="blocked",
                hint="Operator approval required.",
            ),
        ],
    )

    payload = json.loads(checklist.dumps_handoff_json(run))

    assert payload == {
        "schema_version": 1,
            "handoff_to": "yoke onboard project",
        "machine_config_path": str(machine_config),
        "checkout": {"path": str(checkout), "project_id": 7},
        "rows": [
            {
                "id": "machine-config",
                "layer": "machine",
                "title": "Machine config",
                "status": "verified",
            },
            {
                "id": "capability-github",
                "layer": "capability",
                "title": "GitHub capability",
                "status": "blocked",
            },
        ],
    }
