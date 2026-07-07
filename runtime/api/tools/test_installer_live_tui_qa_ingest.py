from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_qa_ingest as qa_ingest
from runtime.api.qa_full_test_helpers import conn_with_rows, make_qa_db_file


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def test_ingest_campaign_dry_run_counts_requirements_runs_and_artifacts(
    tmp_path: Path,
) -> None:
    campaign_root = _write_campaign(tmp_path)

    result = qa_ingest.ingest_campaign(
        campaign_root=campaign_root,
        target=qa_ingest.QATarget(deployment_run_id="campaign-001"),
        execute=False,
    )

    assert result["dry_run"] is True
    assert result["requirement_count"] == 2
    assert result["run_count"] == 1
    assert result["artifact_count"] == 3
    assert result["evidence_ok"] is True


def test_ingest_campaign_execute_writes_qa_rows(
    tmp_path: Path,
    db_path: str,
) -> None:
    campaign_root = _write_campaign(tmp_path)

    result = qa_ingest.ingest_campaign(
        campaign_root=campaign_root,
        target=qa_ingest.QATarget(deployment_run_id="campaign-001"),
        execute=True,
        db_path=db_path,
    )

    assert result["dry_run"] is False
    assert result["created_requirement_count"] == 2
    assert result["reused_requirement_count"] == 0
    assert len(result["run_ids"]) == 1
    assert len(result["artifact_ids"]) == 3

    conn = conn_with_rows(db_path)
    try:
        reqs = conn.execute(
            "SELECT qa_kind, deployment_run_id, suite_id, success_policy, "
            "capability_requirements FROM qa_requirements ORDER BY id"
        ).fetchall()
        runs = conn.execute(
            "SELECT qa_kind, verdict, raw_result, duration_ms FROM qa_runs"
        ).fetchall()
        artifacts = conn.execute(
            "SELECT artifact_type, content_type, artifact_handle, metadata "
            "FROM qa_artifacts ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert [row["qa_kind"] for row in reqs] == ["live-tui", "live-tui"]
    assert {row["deployment_run_id"] for row in reqs} == {"campaign-001"}
    assert {row["suite_id"] for row in reqs} == {"yoke.installer-live-tui"}
    policies = [json.loads(row["success_policy"]) for row in reqs]
    assert [policy["scenario"]["id"] for policy in policies] == [
        "INSTALL-SMOKE-001",
        "AUTH-007",
    ]
    assert json.loads(reqs[0]["capability_requirements"]) == [
        "public-installer",
        "screenshot",
        "ssh",
    ]
    assert len(runs) == 1
    assert runs[0]["qa_kind"] == "live-tui"
    assert runs[0]["verdict"] == "pass"
    assert json.loads(runs[0]["raw_result"])["scenario_id"] == "INSTALL-SMOKE-001"
    assert runs[0]["duration_ms"] == 2000
    assert [row["artifact_type"] for row in artifacts] == [
        "report",
        "log",
        "screenshot",
    ]
    handles = [json.loads(row["artifact_handle"]) for row in artifacts]
    assert all(handle["backend"] == "local" for handle in handles)
    assert handles[1]["path"].endswith("captures/A001/INSTALL-SMOKE-001/000.txt")
    assert json.loads(artifacts[2]["metadata"])["source"] == "screenshot"


def test_ingest_campaign_reuses_existing_requirements(
    tmp_path: Path,
    db_path: str,
) -> None:
    campaign_root = _write_campaign(tmp_path)
    target = qa_ingest.QATarget(deployment_run_id="campaign-001")

    first = qa_ingest.ingest_campaign(
        campaign_root=campaign_root,
        target=target,
        execute=True,
        db_path=db_path,
    )
    second = qa_ingest.ingest_campaign(
        campaign_root=campaign_root,
        target=target,
        execute=True,
        db_path=db_path,
    )

    assert first["created_requirement_count"] == 2
    assert second["created_requirement_count"] == 0
    assert second["reused_requirement_count"] == 2
    conn = conn_with_rows(db_path)
    try:
        req_count = conn.execute("SELECT COUNT(*) FROM qa_requirements").fetchone()[0]
        run_count = conn.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]
    finally:
        conn.close()
    assert req_count == 2
    assert run_count == 2


def test_ingest_campaign_rejects_incomplete_evidence(
    tmp_path: Path,
    db_path: str,
) -> None:
    campaign_root = _write_campaign(tmp_path, include_screenshot=False)

    with pytest.raises(ValueError, match="campaign evidence is incomplete"):
        qa_ingest.ingest_campaign(
            campaign_root=campaign_root,
            target=qa_ingest.QATarget(deployment_run_id="campaign-001"),
            execute=True,
            db_path=db_path,
        )


def test_ingest_campaign_rejects_partial_epic_target(tmp_path: Path) -> None:
    campaign_root = _write_campaign(tmp_path)

    with pytest.raises(ValueError, match="epic-id and --task-num"):
        qa_ingest.ingest_campaign(
            campaign_root=campaign_root,
            target=qa_ingest.QATarget(epic_id=50),
            execute=False,
        )


def _write_campaign(
    tmp_path: Path,
    *,
    include_screenshot: bool = True,
) -> Path:
    campaign_root = tmp_path / "campaign"
    manifest = {
        "harness_id": "installer-live-tui",
        "suite_id": "yoke.installer-live-tui",
        "version": "0.1",
        "target_env": "stage",
        "scenarios": [
            {
                "id": "INSTALL-SMOKE-001",
                "wave": "Wave 1: Installer And First Wizard Smoke",
                "host_profile": "bare-no-uv",
                "flow": "Interactive installer",
                "assertions": "welcome renders",
                "qa_kind": "live-tui",
                "executor_type": "agent",
                "target_env": "stage",
                "blocking_mode": "blocking",
                "capability_requirements": [
                    "public-installer",
                    "screenshot",
                    "ssh",
                ],
                "success_policy": {
                    "type": "composite",
                    "steps": [{"name": "initial", "evidence": ["text_capture"]}],
                },
            },
            {
                "id": "AUTH-007",
                "wave": "Wave 5: Auth And Token Handling",
                "host_profile": "prepared-git",
                "flow": "invalid token",
                "assertions": "friendly error",
                "qa_kind": "live-tui",
                "executor_type": "agent",
                "target_env": "stage",
                "blocking_mode": "blocking",
                "capability_requirements": ["github", "screenshot", "ssh"],
                "success_policy": {
                    "type": "composite",
                    "steps": [{"name": "screen_flow", "evidence": ["text_capture"]}],
                },
            },
        ],
    }
    capture_path = (
        campaign_root / "captures" / "A001" / "INSTALL-SMOKE-001" / "000.txt"
    )
    screenshot_path = (
        campaign_root / "screenshots" / "A001" / "INSTALL-SMOKE-001" / "000.png"
    )
    capture_path.parent.mkdir(parents=True)
    capture_path.write_text("Set up your machine\n", encoding="utf-8")
    if include_screenshot:
        screenshot_path.parent.mkdir(parents=True)
        screenshot_path.write_bytes(b"png")
    report = {
        "assignment_id": "A001",
        "campaign_root": str(campaign_root),
        "host_id": "tui-linux-001",
        "started_at": "2026-07-04T08:00:00Z",
        "completed_at": "2026-07-04T08:00:02Z",
        "overall_result": "pass",
        "scenarios": [
            {
                "scenario_id": "INSTALL-SMOKE-001",
                "result": "pass",
                "captures": [
                    {
                        "name": capture_path.name,
                        "path": str(capture_path),
                        "sha256": "capture-sha",
                        "bytes": 20,
                    }
                ],
                "screenshots": [
                    {
                        "name": screenshot_path.name,
                        "path": str(screenshot_path),
                        "sha256": "screenshot-sha",
                        "bytes": 3,
                    }
                ]
                if include_screenshot
                else [],
                "assertions": {"expected_text": ["Set up your machine"]},
                "failure": "",
            }
        ],
    }
    (campaign_root / "reports").mkdir(parents=True)
    json_helper.dump_path(campaign_root / "harness-manifest.json", manifest)
    json_helper.dump_path(campaign_root / "reports" / "A001.json", report)
    return campaign_root
