"""Item-detail QA must surface a CI run conclusion as openable proof."""

from __future__ import annotations

import json

from yoke_core.domain import item_detail_read
from runtime.api.item_page_reads_test_support import _connection

SHA = "f81d1ad1a61c" + "0" * 28
RUN_URL = "https://github.test/upyoke/yoke/actions/runs/399"


def test_detail_qa_projects_ci_conclusion_without_inventing_artifacts(
    monkeypatch,
):
    conn = _connection()
    conn.execute(
        "INSERT INTO qa_requirements "
        "(id, item_id, qa_kind, requirement_source, success_policy, "
        "created_at, method_id, expected_outcome) "
        "VALUES (8, 51, 'plan_case', 'backend-suite', '{}', "
        "'now', 'command', 'The suite passes on CI.')"
    )
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (107, 8, 'ci_run', 'pass', ?)",
        (
            json.dumps(
                {
                    "ci_run_id": "399",
                    "ci_conclusion": "success",
                    "run_url": RUN_URL,
                    "exit_code": 0,
                    "verification_tree": {"head_sha": SHA},
                }
            ),
        ),
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)
    rows = {row["requirement_source"]: row for row in item["qa_requirements"]}
    row = rows["backend-suite"]

    assert row["run_id"] == 107
    assert row["artifacts"] == []
    assert row["recorded_head_sha"] == SHA
    assert row["run_url"] == RUN_URL
    assert row["ci_conclusion"] == "success"
    assert row["proof_summary"] == f"verified {SHA[:12]} · GitHub Actions run"
    assert "performed_by" not in row


def test_detail_qa_does_not_treat_an_agent_capture_pointer_as_ci(
    monkeypatch,
):
    conn = _connection()
    conn.execute(
        "INSERT INTO qa_requirements "
        "(id, item_id, qa_kind, requirement_source, success_policy, "
        "created_at, method_id, expected_outcome) "
        "VALUES (9, 51, 'plan_case', 'agent-review', '{}', "
        "'now', 'terminal-inspection', 'The CLI help renders.')"
    )
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (108, 9, 'host_control', 'pass', '{}')"
    )
    conn.execute("INSERT INTO qa_artifacts VALUES (203, 108, 'terminal_screenshot')")
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (109, 9, 'agent', 'pass', "
        "'{\"capture_run_id\": 108}')"
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)
    rows = {row["requirement_source"]: row for row in item["qa_requirements"]}
    row = rows["agent-review"]

    assert row["run_id"] == 109
    assert [artifact["artifact_type"] for artifact in row["artifacts"]] == (
        ["terminal_screenshot"]
    )
    assert row["run_url"] == ""
    assert row["ci_conclusion"] == ""
