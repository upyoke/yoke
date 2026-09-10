"""Item-detail QA evidence must follow a review verdict to its capture run.

A review run rarely captures its own screenshots — it records a verdict
against an earlier immutable capture run and embeds that run's id in its own
``raw_result``. These regression-guard the read model that once stopped at
the review run's bare ``run_id`` and reported "no artifacts attached" even
though the capture run it reviewed owned real evidence.
"""

from yoke_core.domain import item_detail_read
from runtime.api.item_page_reads_test_support import _connection


def test_detail_qa_resolves_agent_review_evidence_to_capture_run(monkeypatch):
    conn = _connection()
    conn.execute("ALTER TABLE qa_runs ADD COLUMN performed_by TEXT")
    conn.execute(
        "INSERT INTO qa_requirements "
        "(id, item_id, qa_kind, requirement_source, success_policy, "
        "created_at, method_id, expected_outcome) "
        "VALUES (5, 51, 'plan_case', 'installed-cli-guidance', '{}', "
        "'now', 'terminal-inspection', 'The CLI help renders.')"
    )
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (100, 5, 'host_control', 'pass', '{}')"
    )
    conn.execute("INSERT INTO qa_artifacts VALUES (200, 100, 'terminal_screenshot')")
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (101, 5, 'agent', 'pass', "
        "'{\"capture_run_id\": 100}')"
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)
    rows = {row["requirement_source"]: row for row in item["qa_requirements"]}
    row = rows["installed-cli-guidance"]

    assert row["run_id"] == 101
    assert [artifact["artifact_type"] for artifact in row["artifacts"]] == (
        ["terminal_screenshot"]
    )
    assert "performed_by" not in row


def test_detail_qa_resolves_human_review_evidence_through_prior_agent_run(
    monkeypatch,
):
    conn = _connection()
    conn.execute("ALTER TABLE qa_runs ADD COLUMN performed_by TEXT")
    conn.execute("ALTER TABLE qa_runs ADD COLUMN verdict_reason TEXT")
    conn.execute(
        "INSERT INTO qa_requirements "
        "(id, item_id, qa_kind, requirement_source, success_policy, "
        "created_at, method_id, expected_outcome) "
        "VALUES (6, 51, 'plan_case', 'operator-clarity-review', '{}', "
        "'now', 'browser-inspection', 'The presentation reads clearly.')"
    )
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (102, 6, 'browser_substrate', 'undetermined', '{}')"
    )
    conn.execute("INSERT INTO qa_artifacts VALUES (201, 102, 'screenshot')")
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (103, 6, 'agent', 'undetermined', "
        "'{\"capture_run_id\": 102}')"
    )
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (104, 6, 'human_review', 'pass', '{}')"
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)
    rows = {row["requirement_source"]: row for row in item["qa_requirements"]}
    row = rows["operator-clarity-review"]

    assert row["run_id"] == 104
    assert [artifact["artifact_type"] for artifact in row["artifacts"]] == (
        ["screenshot"]
    )
