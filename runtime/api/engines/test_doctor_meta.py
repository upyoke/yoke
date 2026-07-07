"""Doctor meta-HCs covering registry, backlog quality, schema, and item flows.

Project FK/JSON/ephemeral/lifecycle HCs live in test_doctor_meta_project.py.
Epic-task/body/dependency/flow HCs live in test_doctor_meta_lifecycle.py.

Schema scaffolding is shared via _doctor_meta_test_helpers (private module).
"""

from __future__ import annotations

import datetime
import json

from yoke_core.engines._doctor_meta_test_helpers import (
    _args,
    _insert_deployment_flow,
    _insert_item,
    _make_conn,
    _results,
)


def _recent_created_at(days_ago: int = 5) -> str:
    # Tests that need an item to be considered fresh against
    # ``backlog_stale_days`` (default 30) compute ``created_at`` relative
    # to now — a hardcoded literal silently ages into staleness as wall
    # time advances past it.
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
from yoke_core.engines.doctor import (
    HEALTH_CHECKS,
    RecordCollector,
    _DELEGATED_SYNC_HCS,
    hc_backlog_quality,
    hc_deploy_stage_integrity,
    hc_flow_stage_json,
    hc_invalid_item_flows,
    hc_schema_drift,
)


class TestHCRegistryCompleteness:
    """AC-2: Verify that the HC registry covers all shell HCs."""

    def test_known_hc_ids_registered(self):
        """Every HC slug in the HEALTH_CHECKS list maps to an 'HC-' prefixed ID."""
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        for s in _DELEGATED_SYNC_HCS:
            slugs.add(s)
        assert "schema-drift" in slugs
        assert "backlog-quality" in slugs
        assert "deploy-stage-integrity" in slugs
        assert "zombie-ephemeral-envs" in slugs
        assert "orphaned-active-items" in slugs
        assert "reviewed-implementation-epics-no-sim" in slugs
        assert "file-line-limit" in slugs
        assert "config-validation" in slugs
        assert "event-registry-coverage" in slugs
        assert "browser-substrate" in slugs
        assert "doc-drift" in slugs
        assert "agent-consistency" in slugs
        assert "hook-executability" in slugs
        assert "self-test" in slugs
        assert "stale-sessions" in slugs
        assert "claudemd-drift" in slugs

    def test_minimum_hc_count(self):
        """Python engine has at least as many HCs as the known shell count."""
        slugs = {hc.slug for hc in HEALTH_CHECKS}
        for s in _DELEGATED_SYNC_HCS:
            slugs.add(s)
        assert len(slugs) >= 108


class TestBacklogQuality:
    def test_pass_healthy_backlog(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, priority, spec, created_at) "
            "VALUES (1, 'Good title here', 'idea', 'medium', '# Good title here\n\nSome body', "
            f"'{_recent_created_at()}')"
        )
        rec = RecordCollector()
        hc_backlog_quality(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-backlog-quality"][0] == "PASS"

    def test_warn_short_title(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, priority, spec, created_at) "
            "VALUES (1, 'Short', 'idea', 'medium', '# Short\n\nBody text', '2026-04-20T00:00:00Z')"
        )
        rec = RecordCollector()
        hc_backlog_quality(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-backlog-quality"][0] == "WARN"
        assert "title too short" in res["HC-backlog-quality"][1]

    def test_fail_no_body_past_idea(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, priority, spec, created_at) "
            "VALUES (1, 'Enough title text', 'implementing', 'medium', '', '2026-04-20T00:00:00Z')"
        )
        rec = RecordCollector()
        hc_backlog_quality(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-backlog-quality"][0] == "FAIL"

    def test_no_body_cancelled_item_not_fail(self):
        # Cancelled items are terminal-exceptional — they never received a
        # body and never will. They must not trip the body-required FAIL
        # branch.
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, priority, spec, created_at) "
            "VALUES (1, 'Enough title text', 'cancelled', 'medium', '', '2026-04-20T00:00:00Z')"
        )
        rec = RecordCollector()
        hc_backlog_quality(conn, _args(), rec)
        res = _results(rec)
        # Must not FAIL (PASS or WARN both acceptable; the key invariant
        # is that the cancelled item does not push the HC into FAIL).
        assert res["HC-backlog-quality"][0] in ("PASS", "WARN")
        assert "no body content at status 'cancelled'" not in res["HC-backlog-quality"][1]

    def test_no_body_rejected_item_not_fail(self):
        # Rejected items mirror cancelled — exempt from the body-required
        # FAIL branch.
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, priority, spec, created_at) "
            "VALUES (1, 'Enough title text', 'rejected', 'medium', '', '2026-04-20T00:00:00Z')"
        )
        rec = RecordCollector()
        hc_backlog_quality(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-backlog-quality"][0] in ("PASS", "WARN")
        assert "no body content at status 'rejected'" not in res["HC-backlog-quality"][1]


class TestSchemaScriptSyncSample:
    """Simplified test for schema-drift: just verify it runs and reports."""

    def test_schema_drift_pass_correct_schema(self):
        """When all expected tables/columns exist, should PASS."""
        conn = _make_conn()
        rec = RecordCollector()
        hc_schema_drift(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-schema-drift"][0] in ("PASS", "WARN")


class TestDeployStageIntegrity:
    def test_pass_no_deploy_stage(self):
        """Pass when deploy_stage column exists but no problematic items."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, deploy_stage) "
            "VALUES (1, 'Test', 'done', 'complete')"
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES ('run-1', 1, '2026-04-20T00:00:00Z')"
        )
        rec = RecordCollector()
        hc_deploy_stage_integrity(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-deploy-stage-integrity"][0] == "PASS"


class TestFlowStageJson:
    def test_pass_valid_json(self):
        conn = _make_conn()
        _insert_deployment_flow(
            conn, "f1", stages=json.dumps([{"name": "build"}])
        )
        rec = RecordCollector()
        hc_flow_stage_json(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-flow-stage-json"][0] == "PASS"

    def test_fail_invalid_json(self):
        conn = _make_conn()
        _insert_deployment_flow(conn, "f1", stages="not json {")
        rec = RecordCollector()
        hc_flow_stage_json(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-flow-stage-json"][0] == "FAIL"


class TestInvalidItemFlows:
    def test_pass_valid_flow(self):
        conn = _make_conn()
        _insert_deployment_flow(conn, "f1")
        _insert_item(conn, 1, deployment_flow="f1")
        rec = RecordCollector()
        hc_invalid_item_flows(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-invalid-item-flows"][0] == "PASS"

    def test_warn_nonexistent_flow(self):
        conn = _make_conn()
        _insert_item(conn, 1, deployment_flow="missing-flow")
        rec = RecordCollector()
        hc_invalid_item_flows(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-invalid-item-flows"][0] == "WARN"
