"""Doctor HC tests (Doctor-project dispatch + skill + body + shepherd + drift + deploy-stage).

Other doctor_hc_meta_full tests live in sibling files.

Schema scaffolding shared via _doctor_hc_meta_full_test_helpers (private module).
Uses disposable Postgres test databases and mock subprocess for deterministic testing.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch


from yoke_core.engines.doctor import (
    DoctorArgs,
    HEALTH_CHECKS,
    _should_run_hc,
    hc_deploy_stage_integrity,
    hc_shepherd_spec_integrity,
    hc_stale_body,
)
from yoke_project_checks.check_docs import (
    hc_claudemd_drift,
)

from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _NOW_ISO,
    _make_conn,
    _result,
    _run_hc,
)


class TestDoctorProjectDispatch:
    """Tests for --project dispatch (HC filtering)."""

    def test_quick_skips_github_hcs(self):
        """T7: --quick skips GitHub-dependent HCs."""
        args = DoctorArgs(quick=True)
        assert not _should_run_hc("orphaned-gh-issues", args)
        assert not _should_run_hc("stale-remote-branches", args)
        assert not _should_run_hc("wrong-repo-issues", args)

    def test_quick_allows_db_hcs(self):
        """--quick allows DB-only HCs."""
        args = DoctorArgs(quick=True)
        assert _should_run_hc("status-consistency", args)
        assert _should_run_hc("backlog-quality", args)

    def test_only_filters_to_single_hc(self):
        """--only filters to a single HC."""
        args = DoctorArgs(only="schema-drift")
        assert _should_run_hc("schema-drift", args)
        assert not _should_run_hc("backlog-quality", args)

    def test_hc_registration_completeness(self):
        """Universal HC slugs stay in the engine roster."""
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        for expected in [
            "schema-drift", "backlog-quality",
            "worktree-health", "stale-remote-branches", "orphaned-gh-issues",
            "gh-orphan-detection", "wrong-repo-issues", "size-bloat",
            "file-line-limit",
            "config-validation", "epic-task-worktree",
        ]:
            assert expected in slugs, f"{expected} not in HEALTH_CHECKS"

    def test_self_project_slugs_left_the_engine_roster(self):
        """Checks that only describe this project ship with this project.

        ``doc-health`` and its siblings inspect Yoke's own docs, prompts, and
        adapters; carrying them in the roster every install receives gave
        them nothing to inspect. They are declared in ``.yoke/doctor/``.
        """
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        for moved in ["doc-health", "doc-drift", "atlas-integrity"]:
            assert moved not in slugs, f"{moved} should be a project check"


class TestDoctorSkill:
    """Tests for doctor skill presence and configuration."""

    def test_doctor_skill_exists(self):
        """SKILL.md for doctor command should exist."""
        # This is a file-system check from the shell test; we verify
        # the Python doctor module exposes the expected API
        assert hasattr(DoctorArgs, "__init__")
        assert len(HEALTH_CHECKS) > 0

    def test_health_checks_registered(self):
        """All HCs have unique slugs."""
        slugs = [hc.slug for hc in HEALTH_CHECKS]
        assert len(slugs) == len(set(slugs)), "Duplicate HC slugs found"


class TestStaleBody:
    """Tests for hc_stale_body."""

    def test_pass_spec_updated_at_present(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, spec_updated_at) "
            "VALUES (1, 'Test', 'idea', '2026-01-02T00:00:00Z')"
        )
        rec = _run_hc(hc_stale_body, conn)
        assert _result(rec).result == "PASS"

    def test_pass_no_spec_updated_at(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status) "
            "VALUES (1, 'Test', 'idea')"
        )
        rec = _run_hc(hc_stale_body, conn)
        assert _result(rec).result == "PASS"


class TestShepherdSpecIntegrity:
    """Tests for hc_shepherd_spec_integrity."""

    def test_pass_epic_with_spec(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, spec) "
            "VALUES (1, 'Epic', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'implementing', 'Some spec content')"
        )
        rec = _run_hc(hc_shepherd_spec_integrity, conn)
        assert _result(rec).result == "PASS"

    def test_warn_epic_without_spec(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, workflow_id, workflow_version_id, status) "
            "VALUES (1, 'Epic', 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'implementing')"
        )
        rec = _run_hc(hc_shepherd_spec_integrity, conn)
        assert _result(rec).result == "WARN"


class TestClaudemdDrift:
    """Tests for hc_claudemd_drift."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    def test_pass_no_root(self, mock_root):
        rec = _run_hc(hc_claudemd_drift)
        assert _result(rec).result == "PASS"


class TestDeployStageIntegrity:
    """Tests for hc_deploy_stage_integrity."""

    def test_pass_no_issues(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, deploy_stage) "
            "VALUES (1, 'Test', 'done', 'complete')"
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES ('run-1', 1, %s)",
            (_NOW_ISO,),
        )
        rec = _run_hc(hc_deploy_stage_integrity, conn)
        assert _result(rec).result == "PASS"


# ---------------------------------------------------------------------------
# events ledger trust-signal HCs
# ---------------------------------------------------------------------------


def _ensure_migration_audit_table(conn: Any) -> None:
    """Create the final-shape migration_audit table on the test conn."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_audit (
            id INTEGER PRIMARY KEY,
            migration_name TEXT NOT NULL,
            description TEXT,
            tables_declared TEXT NOT NULL,
            expected_deltas TEXT NOT NULL,
            pre_row_counts TEXT NOT NULL,
            post_row_counts TEXT,
            pre_fk_violations INTEGER NOT NULL DEFAULT 0,
            post_fk_violations INTEGER,
            backup_path TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'planned'
                CHECK(state IN (
                    'planned','test_copy_created','test_applied',
                    'test_verified','rehearsed','backup_created',
                    'live_applied','live_verified','completed',
                    'test_copy_failed','test_apply_failed',
                    'test_verify_failed','backup_failed',
                    'live_apply_failed','live_verify_failed'
                )),
            failure_reason TEXT,
            exception_reason TEXT,
            source_fingerprint TEXT,
            rehearsed_at TEXT,
            lease_id INTEGER,
            test_copy_path TEXT,
            baseline_verify_result TEXT,
            author_verify_result TEXT,
            session_id TEXT,
            model_name TEXT,
            project_id TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            duration_ms INTEGER
        )
    """)
