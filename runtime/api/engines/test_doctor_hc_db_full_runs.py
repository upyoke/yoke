"""Doctor HC tests (Deploy-stage + runs HCs).

Other doctor_hc_db_full tests live in sibling files (test_doctor_hc_db_full*.py).

Schema scaffolding shared via _doctor_hc_db_full_test_helpers (private module).
"""

from __future__ import annotations


from yoke_core.engines.doctor import (
    hc_deploy_stage_integrity,
    hc_orphaned_runs,
    hc_run_item_status_consistency,
    hc_run_qa_unsatisfied,
    hc_stale_runs,
)
from runtime.api.conftest import (
    insert_deployment_run,
    insert_item,
)

from yoke_core.engines._doctor_hc_db_full_test_helpers import (
    _result,
    _run_hc,
)
from yoke_core.engines._project_identity_test_helpers import _seed_project


class TestHCDeployStageIntegrity:
    """Tests for HC-deploy-stage-integrity."""

    def _add_project(self, conn, project_id):
        _seed_project(conn, project_id)
        conn.commit()

    def test_pass_no_complete_items(self, test_db):
        """Test 1: PASS when no items have deploy_stage=complete."""
        insert_item(test_db, id=1, title="Normal done item test", status="done")
        rec = _run_hc(hc_deploy_stage_integrity, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_complete_no_evidence(self, test_db):
        """Test 2: WARN when deploy_stage=complete but no deployment evidence."""
        insert_item(test_db, id=10, title="Item with no evidence test",
                    status="done", deployment_flow="externalwebapp-release",
                    deploy_stage="complete",
                    created_at="2026-03-17T00:00:00Z")
        rec = _run_hc(hc_deploy_stage_integrity, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "YOK-10" in r.detail

    def test_pass_complete_with_runs(self, test_db):
        """Test 3: PASS when deploy_stage=complete with matching deployment_runs."""
        self._add_project(test_db, "externalwebapp")
        insert_item(test_db, id=20, title="Item with runs test item",
                    status="done", deployment_flow="externalwebapp-release",
                    deploy_stage="complete",
                    created_at="2026-03-17T00:00:00Z")
        insert_deployment_run(test_db, id="run-t3-20", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded")
        test_db.execute("INSERT INTO deployment_run_items (run_id, item_id, added_at) VALUES (%s, %s, '2026-01-01T00:00:00Z')",
                        ("run-t3-20", 20))
        test_db.commit()
        rec = _run_hc(hc_deploy_stage_integrity, test_db)
        assert _result(rec).result == "PASS"

    def test_mixed_some_with_some_without(self, test_db):
        """Test 4: Mixed - only items without evidence are flagged."""
        self._add_project(test_db, "externalwebapp")
        insert_item(test_db, id=30, title="Has runs item test",
                    status="done", deployment_flow="externalwebapp-release",
                    deploy_stage="complete",
                    created_at="2026-03-17T00:00:00Z")
        insert_item(test_db, id=31, title="No runs item test",
                    status="done", deployment_flow="externalwebapp-internal",
                    deploy_stage="complete",
                    created_at="2026-03-17T00:00:00Z")
        insert_deployment_run(test_db, id="run-t4-30", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded")
        test_db.execute("INSERT INTO deployment_run_items (run_id, item_id, added_at) VALUES (%s, %s, '2026-01-01T00:00:00Z')",
                        ("run-t4-30", 30))
        test_db.commit()
        rec = _run_hc(hc_deploy_stage_integrity, test_db)
        r = _result(rec)
        assert "YOK-31" in r.detail
        assert "YOK-30" not in r.detail

    def test_non_complete_stage_not_flagged(self, test_db):
        """Test 5: Items with non-complete deploy_stage not flagged."""
        insert_item(test_db, id=40, title="In progress deploy test",
                    status="implementing", deployment_flow="externalwebapp-release",
                    deploy_stage="build")
        rec = _run_hc(hc_deploy_stage_integrity, test_db)
        assert _result(rec).result == "PASS"

    def test_complete_null_flow_flagged(self, test_db):
        """Test 6: deploy_stage=complete with null deployment_flow still flagged."""
        insert_item(test_db, id=50, title="No flow set item test",
                    status="done", deploy_stage="complete",
                    created_at="2026-03-17T00:00:00Z")
        rec = _run_hc(hc_deploy_stage_integrity, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "YOK-50" in r.detail


class TestHCOrphanedRunsFull:
    """Tests for HC-orphaned-runs."""

    def _add_project(self, conn, project_id="externalwebapp"):
        _seed_project(conn, project_id)
        conn.commit()

    def test_pass_all_runs_have_items(self, test_db):
        """Test 1: PASS when all runs have items."""
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-1", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded")
        test_db.execute("INSERT INTO deployment_run_items (run_id, item_id, added_at) VALUES (%s, %s, '2026-01-01T00:00:00Z')",
                        ("run-1", 1))
        test_db.commit()
        rec = _run_hc(hc_orphaned_runs, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_run_no_items(self, test_db):
        """Test 2: WARN when an item-less run never started executing."""
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-empty", project="externalwebapp",
                              flow="externalwebapp-release", status="created")
        rec = _run_hc(hc_orphaned_runs, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "run-empty" in r.detail

    def test_pass_no_runs(self, test_db):
        """Test 3: PASS when no runs exist."""
        rec = _run_hc(hc_orphaned_runs, test_db)
        assert _result(rec).result == "PASS"

    def test_pass_itemless_executed_run(self, test_db):
        """Item-less runs that executed are environment-level deploys."""
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-env", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded")
        rec = _run_hc(hc_orphaned_runs, test_db)
        assert _result(rec).result == "PASS"


class TestHCStaleRunsFull:
    """Tests for HC-stale-runs."""

    def _add_project(self, conn, project_id="externalwebapp"):
        _seed_project(conn, project_id)
        conn.commit()

    def test_pass_no_stale_runs(self, test_db):
        """Test 4: PASS when no stale runs."""
        # Use a relative timestamp so the fixture stays fresh regardless of
        # wall clock (HC-stale-runs uses a 24h threshold).
        from datetime import datetime, timedelta, timezone

        fresh_iso = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-fresh", project="externalwebapp",
                              flow="externalwebapp-release", status="executing",
                              started_at=fresh_iso)
        rec = _run_hc(hc_stale_runs, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_stale_run(self, test_db):
        """Test 5: WARN when run executing for >24h."""
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-stale", project="externalwebapp",
                              flow="externalwebapp-release", status="executing",
                              started_at="2026-03-01T00:00:00Z",
                              current_stage="deploy")
        rec = _run_hc(hc_stale_runs, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "run-stale" in r.detail

    def test_succeeded_runs_not_flagged(self, test_db):
        """Test 6: Succeeded runs not flagged as stale."""
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-done", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded",
                              started_at="2026-03-01T00:00:00Z",
                              completed_at="2026-03-01T01:00:00Z")
        rec = _run_hc(hc_stale_runs, test_db)
        assert _result(rec).result == "PASS"


class TestHCRunItemStatusConsistencyFull:
    """Tests for HC-run-item-status-consistency."""

    def _add_project(self, conn, project_id="externalwebapp"):
        _seed_project(conn, project_id)
        conn.commit()

    def test_pass_consistent(self, test_db):
        """Test 7: PASS when statuses are consistent."""
        self._add_project(test_db)
        insert_item(test_db, id=1, title="Release item status test", status="release")
        insert_deployment_run(test_db, id="run-1", project="externalwebapp",
                              flow="externalwebapp-release", status="executing",
                              started_at="2026-04-08T00:00:00Z")
        test_db.execute("INSERT INTO deployment_run_items (run_id, item_id, added_at) VALUES (%s, %s, '2026-01-01T00:00:00Z')",
                        ("run-1", 1))
        test_db.commit()
        rec = _run_hc(hc_run_item_status_consistency, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_release_not_in_run(self, test_db):
        """Test 8: WARN when item at release but not in executing run."""
        insert_item(test_db, id=10, title="Orphan release item test", status="release")
        rec = _run_hc(hc_run_item_status_consistency, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "YOK-10" in r.detail

    def test_warn_implemented_in_executing_run(self, test_db):
        """Test 9: WARN when item is still implemented inside an executing run."""
        self._add_project(test_db)
        insert_item(test_db, id=20, title="Implemented item test", status="implemented")
        insert_deployment_run(test_db, id="run-implemented", project="externalwebapp",
                              flow="externalwebapp-release", status="executing",
                              started_at="2026-04-08T00:00:00Z")
        test_db.execute("INSERT INTO deployment_run_items (run_id, item_id, added_at) VALUES (%s, %s, '2026-01-01T00:00:00Z')",
                        ("run-implemented", 20))
        test_db.commit()
        rec = _run_hc(hc_run_item_status_consistency, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "status=implemented" in r.detail

    def test_warn_done_but_run_failed(self, test_db):
        """Test 10: WARN when item at done but run not succeeded."""
        self._add_project(test_db)
        insert_item(test_db, id=30, title="Done but run failed test", status="done")
        insert_deployment_run(test_db, id="run-fail", project="externalwebapp",
                              flow="externalwebapp-release", status="failed",
                              completed_at="2026-04-08T00:00:00Z")
        test_db.execute("INSERT INTO deployment_run_items (run_id, item_id, added_at) VALUES (%s, %s, '2026-01-01T00:00:00Z')",
                        ("run-fail", 30))
        test_db.commit()
        rec = _run_hc(hc_run_item_status_consistency, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "YOK-30" in r.detail


class TestHCRunQAUnsatisfiedFull:
    """Tests for HC-run-qa-unsatisfied."""

    def _add_project(self, conn, project_id="externalwebapp"):
        _seed_project(conn, project_id)
        conn.commit()

    def test_pass_no_pending_qa(self, test_db):
        """Test 11: PASS when no pending blocking QA."""
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-clean", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded")
        test_db.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, blocking, status) "
            "VALUES (%s, %s, %s, %s)",
            ("run-clean", "smoke-test", 1, "passed"),
        )
        test_db.commit()
        rec = _run_hc(hc_run_qa_unsatisfied, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_pending_blocking_qa(self, test_db):
        """Test 12: WARN when succeeded run has pending blocking QA."""
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-qa", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded")
        test_db.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, blocking, status) "
            "VALUES (%s, %s, %s, %s)",
            ("run-qa", "smoke-test", 1, "pending"),
        )
        test_db.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, blocking, status) "
            "VALUES (%s, %s, %s, %s)",
            ("run-qa", "health-check", 1, "passed"),
        )
        test_db.commit()
        rec = _run_hc(hc_run_qa_unsatisfied, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "smoke-test" in r.detail

    def test_non_blocking_pending_not_flagged(self, test_db):
        """Test 13: Non-blocking pending QA not flagged."""
        self._add_project(test_db)
        insert_deployment_run(test_db, id="run-nb", project="externalwebapp",
                              flow="externalwebapp-release", status="succeeded")
        test_db.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, blocking, status) "
            "VALUES (%s, %s, %s, %s)",
            ("run-nb", "optional-check", 0, "pending"),
        )
        test_db.commit()
        rec = _run_hc(hc_run_qa_unsatisfied, test_db)
        assert _result(rec).result == "PASS"
