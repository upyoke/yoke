"""Item overview and detail read-model tests."""

from yoke_core.domain import item_detail_read, item_overview_read
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from runtime.api.item_page_reads_test_support import _connection


def test_overview_enrichment_keeps_owner_and_live_claim_distinct(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(
        item_overview_read.db_helpers,
        "connect",
        lambda: conn,
    )
    rows = item_overview_read.enrich_item_overview_rows(
        [
            {
                "id": "51",
                "title": "Fix the footer",
                "workflow_id": "dash",
                "workflow_version_id": "11",
                "status": "reviewing-implementation",
                "project": "acme",
            }
        ]
    )

    assert rows[0]["public_ref"] == "ACM-22"
    assert rows[0]["project_name"] == "Acme"
    assert rows[0]["owner"] == "Rae"
    assert rows[0]["stage_label"] == "reviewing implementation"
    assert rows[0]["claimed_by"]["actor_label"] == "Codex"
    assert rows[0]["claimed_by"]["session_id"] == "session-z"
    assert rows[0]["worktrees"][0]["branch"] == "codex/footer"
    assert rows[0]["worktrees"][0]["lane_role"] == "implementation"
    assert rows[0]["worktrees"][0]["state"] == "active"


def test_detail_read_assembles_real_workflow_lanes_and_proof(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)
    item = item_detail_read.get_item_detail(51)

    assert item["public_ref"] == "ACM-22"
    assert item["title"] == "Fix the footer"
    assert item["workflow"]["id"] == "dash"
    assert item["workflow"]["version"] == builtin_workflow_definition("dash")[
        "version"
    ]
    assert item["workflow"]["stage_label"] == "reviewing implementation"
    assert item["workflow"]["executor_id"] == "dash"
    assert item["workflow"]["next_executor_id"] is None
    assert item["workflow"]["item_posture"] == {
        "verification": True,
        "file_budget": True,
    }
    assert item["claim"]["actor_label"] == "Codex"
    assert item["worktrees"][0]["branch"] == "codex/footer"
    assert item["path_claims"] == {"total": 1, "states": {"planned": 1}}
    assert item["file_budget"] == {
        "total": 1,
        "paths": ["packages/web/footer.js"],
    }
    assert item["progress_log"]["content"].endswith("built")
    assert item["qa_requirements"][0]["requirement_source"] == "footer-renders"
    assert item["qa_requirements"][0]["verdict"] == "needs review"
    assert item["qa_requirements"][0]["plan_slug"] == "browser-close"
    assert item["qa_requirements"][0]["plan_name"] == "Browser closeout"
    assert item["qa_requirements"][0]["plan_case_key"] == "responsive-footer"
    assert (
        item["qa_requirements"][0]["workflow_transition_id"]
        == "reviewing-implementation"
    )
    assert item["qa_requirements"][0]["method_name"] == "Browser inspection"
    assert item["qa_requirements"][0]["evidence_count"] == 1
    assert item["qa_requirements"][0]["latest_evidence_type"] == "screenshot"
    assert item["qa_requirements"][0]["outcome"] == "needs_review"
    assert item["qa_requirements"][0]["proof_summary"] == "1 screenshot"
    assert item["qa_requirements"][0]["precondition_reason"] is None
    assert item["qa_plan_attachments"] == [
        {
            "plan_id": 12,
            "transition_id": "reviewing-implementation",
            "qa_phase": "verification",
            "attached_at": "2026-07-25T09:00:00Z",
            "plan_slug": "browser-close",
            "plan_name": "Browser closeout",
            "source": "project default",
            "case_count": 1,
            "materialized_count": 1,
            "materialized_at": "2026-07-26T10:30:00Z",
        }
    ]
    assert "Correct the footer" in item["narrative"]["spec"]


def test_detail_proof_summarizes_current_runs_and_no_run_fallback(monkeypatch):
    conn = _connection()
    requirements = [
        (
            5,
            "terminal-inspection",
            "welcome-frame",
            None,
            "The welcome frame should match.",
        ),
        (
            6,
            "machine-state-check",
            "path-on-shell",
            "fresh-host",
            "The command should be on PATH.",
        ),
        (
            7,
            "terminal-check",
            "cold-start-hosted",
            "fresh-host",
            "The hosted cold start should finish.",
        ),
        (
            8,
            "command",
            "not-started",
            None,
            "This expected prose is not execution proof.",
        ),
        (
            9,
            "machine-state-check",
            "recorded-precondition",
            "fresh-host",
            "The command should be on PATH.",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO qa_requirements (
          id, item_id, qa_kind, qa_phase, blocking_mode,
          requirement_source, success_policy, created_at, method_id,
          expected_outcome, host_baseline
        ) VALUES (?, 51, ?, 'verification', 'blocking', ?, '{}', 'now',
                  ?, ?, ?)
        """,
        [
            (
                requirement_id,
                method_id,
                source,
                method_id,
                expected_outcome,
                host_baseline,
            )
            for (
                requirement_id,
                method_id,
                source,
                host_baseline,
                expected_outcome,
            ) in requirements
        ],
    )
    conn.executemany(
        """
        INSERT INTO qa_runs (
          id, qa_requirement_id, verdict, execution_status, completed_at,
          case_outcome, capture_degraded_reason, raw_result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                9,
                5,
                "pass",
                "captured",
                "now",
                "passed",
                "image capture blocked on the host",
                "{}",
            ),
            (
                10,
                6,
                "inconclusive",
                "captured",
                "now",
                "blocked_on_precondition",
                None,
                '{"error_code":"capability_went_error"}',
            ),
            (
                11,
                7,
                None,
                "running",
                None,
                "running",
                None,
                '{"lease_summary":"Test Mac leased",'
                '"evidence_summary":"transcript + screenshots"}',
            ),
            (
                12,
                9,
                "inconclusive",
                "captured",
                "now",
                "blocked_on_precondition",
                None,
                '{"error_code":"capability_went_error",'
                '"proof_summary":"baseline unverified yesterday, capability '
                'went error; rerun queued behind the lease"}',
            ),
        ],
    )
    conn.execute("INSERT INTO qa_artifacts VALUES (23, 9, 'terminal_text_capture')")
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)
    rows = {row["requirement_source"]: row for row in item["qa_requirements"]}

    assert rows["welcome-frame"]["outcome"] == "passed"
    assert rows["welcome-frame"]["proof_summary"] == (
        "text capture + reason — image capture blocked on the host"
    )
    assert rows["path-on-shell"]["outcome"] == "blocked_on_precondition"
    assert rows["path-on-shell"]["precondition_reason"] == ("capability_went_error")
    assert rows["path-on-shell"]["proof_summary"] == (
        "baseline fresh-host capability went error — case did not run"
    )
    assert rows["cold-start-hosted"]["outcome"] == "running"
    assert rows["cold-start-hosted"]["proof_summary"] == (
        "Test Mac leased · transcript + screenshots"
    )
    assert "raw_result" not in rows["cold-start-hosted"]
    assert rows["not-started"]["outcome"] == "queued"
    assert rows["not-started"]["proof_summary"] == "not run"
    assert rows["recorded-precondition"]["proof_summary"] == (
        "baseline unverified yesterday, capability went error; "
        "rerun queued behind the lease"
    )


def test_detail_read_preserves_engine_wait_state_without_executor(monkeypatch):
    conn = _connection()
    conn.execute("UPDATE items SET status = 'blocked', blocked = 1 WHERE id = 51")
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)

    assert item["workflow"]["stage_id"] == "blocked"
    assert item["workflow"]["stage_label"] == "blocked"
    assert item["workflow"]["executor_id"] is None
    assert item["workflow"]["next_executor_id"] is None


def test_item_plan_attachment_overrides_matching_project_default(monkeypatch):
    conn = _connection()
    conn.execute(
        """
        INSERT INTO qa_plan_item_attachments VALUES (
          51, 'reviewing-implementation', 'manual_acceptance', 12,
          '2026-07-26T09:30:00Z'
        )
        """
    )
    conn.commit()
    monkeypatch.setattr(item_detail_read.db_helpers, "connect", lambda: conn)

    item = item_detail_read.get_item_detail(51)

    assert len(item["qa_plan_attachments"]) == 1
    attachment = item["qa_plan_attachments"][0]
    assert attachment["source"] == "item attachment"
    assert attachment["qa_phase"] == "manual_acceptance"
    assert attachment["attached_at"] == "2026-07-26T09:30:00Z"
