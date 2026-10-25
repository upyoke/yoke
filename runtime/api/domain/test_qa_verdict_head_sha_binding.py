"""QA summaries disclose the scope of their proof reading."""

from yoke_core.domain.qa_gate_summary import _format_text


def test_gate_summary_text_discloses_that_it_skips_tree_freshness():
    text = _format_text(
        {
            "target": "YOK-1",
            "transition": "reviewed-implementation",
            "qa_tables_present": True,
            "no_requirements": False,
            "satisfied": True,
            "blocking_unsatisfied_count": 0,
            "browser_unsatisfied_count": 0,
            "e2e_unsatisfied_count": 0,
            "tree_freshness_checked": False,
            "requirements": [],
        }
    )

    assert "Tree freshness: not evaluated here" in text


def test_recorded_pass_without_commit_is_accepted():
    from runtime.api.fixtures.pg_testdb import test_database
    from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement
    from runtime.api.test_qa_capture_verdict_in_place import _record_agent_verdict

    with test_database() as conn:
        item = insert_item(conn)
        requirement = insert_qa_requirement(conn, item_id=item["id"])
        outcome = _record_agent_verdict(conn, requirement["id"], {
            "performed_by": "agent", "verdict": "pass", "raw_result": "checked",
        })
        assert outcome.primary_success, outcome.error
        row = conn.execute("SELECT verdict,raw_result FROM qa_runs WHERE qa_requirement_id=%s",
            (requirement["id"],)).fetchone()
        assert row["verdict"] == "pass"
        assert "checked" in row["raw_result"]
