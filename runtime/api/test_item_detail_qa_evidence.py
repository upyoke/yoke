"""Item detail selects actual captures and retains durable judgment audit."""

from yoke_core.domain import item_detail_read
from runtime.api.item_page_reads_test_support import _connection


def test_detail_qa_resolves_agent_review_evidence_to_capture_run(monkeypatch):
    conn = _connection()
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
    conn.execute("INSERT INTO qa_plan_review_verdicts VALUES (5, 100, 101)")
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)
    rows = {row["requirement_source"]: row for row in item["qa_requirements"]}
    row = rows["installed-cli-guidance"]

    assert row["run_id"] == 100
    assert [artifact["artifact_type"] for artifact in row["artifacts"]] == (
        ["terminal_screenshot"]
    )
    assert "performed_by" not in row


def test_detail_qa_resolves_human_decision_on_exact_capture(
    monkeypatch,
):
    conn = _connection()
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
    conn.execute("INSERT INTO qa_plan_review_verdicts VALUES (6, 102, 103)")
    # Human resolution finalizes this exact capture; it adds no actual attempt.
    conn.execute("UPDATE qa_runs SET verdict='pass' WHERE id=102")
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)
    rows = {row["requirement_source"]: row for row in item["qa_requirements"]}
    row = rows["operator-clarity-review"]

    assert row["run_id"] == 102
    assert [artifact["artifact_type"] for artifact in row["artifacts"]] == (
        ["screenshot"]
    )


def test_detail_qa_keeps_self_capturing_agent_attempt(
    monkeypatch,
):
    conn = _connection()
    conn.execute(
        "INSERT INTO qa_requirements "
        "(id, item_id, qa_kind, requirement_source, success_policy, "
        "created_at, method_id, expected_outcome) "
        "VALUES (7, 51, 'plan_case', 'agent-mission-review', '{}', "
        "'now', 'terminal-inspection', 'The mission completes.')"
    )
    conn.execute(
        "INSERT INTO qa_runs (id, qa_requirement_id, performed_by, verdict, "
        "raw_result) VALUES (105, 7, 'agent', 'undetermined', '{}')"
    )
    conn.execute("INSERT INTO qa_artifacts VALUES (202, 105, 'terminal_screenshot')")
    conn.execute("UPDATE qa_runs SET verdict='pass' WHERE id=105")
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)
    rows = {row["requirement_source"]: row for row in item["qa_requirements"]}
    row = rows["agent-mission-review"]

    assert row["run_id"] == 105
    assert [artifact["artifact_type"] for artifact in row["artifacts"]] == (
        ["terminal_screenshot"]
    )
