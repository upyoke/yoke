"""Doctor HC tests (Deferred + flow HCs).

Other doctor_hc_db_full tests live in sibling files (test_doctor_hc_db_full*.py).

Schema scaffolding shared via _doctor_hc_db_full_test_helpers (private module).
"""

from __future__ import annotations

import textwrap

from yoke_core.engines.doctor import (
    hc_deferred_items,
    hc_incomplete_deploy_stage,
    hc_projects_without_flows,
)
from runtime.api.conftest import insert_item

from yoke_core.engines._doctor_hc_db_full_test_helpers import (
    _result,
    _run_hc,
)


_TEST_PROJECT_IDS = {
    "yoke": 1,
    "buzz": 2,
    "proj-a": 10,
    "proj-b": 11,
    "proj-c": 12,
    "proj-d": 13,
    "proj-e": 14,
    "proj-f": 15,
}


def _project_id(slug: str) -> int:
    return _TEST_PROJECT_IDS[slug]


class TestHCDeferredItemsFull:
    """Tests for HC-deferred-items: deferred items enforcement for done epics."""

    def test_pass_no_done_epics(self, test_db):
        """Test 1: PASS when no done epics."""
        insert_item(test_db, id=10, title="Active epic test", type="epic",
                    status="implementing", spec="Some body content")
        rec = _run_hc(hc_deferred_items, test_db)
        assert _result(rec).result == "PASS"

    def test_pass_done_epic_clean_body(self, test_db):
        """Test 2: PASS for done epic with clean body."""
        insert_item(test_db, id=20, title="Clean done epic test", type="epic",
                    status="done", spec="This is a clean epic body with no deferrals.")
        rec = _run_hc(hc_deferred_items, test_db)
        assert "YOK-20" not in _result(rec).detail

    def test_warn_done_epic_unfiled_deferred(self, test_db):
        """Test 3: WARN for done epic with UNFILED deferred items."""
        body = textwrap.dedent("""\
            ## Problem
            Some problem.

            ## Deferred Items

            | Description | Reason | Ticket |
            |---|---|---|
            | Remove column | Migration risk | UNFILED |

            ## Shepherd Log
            Done.""")
        insert_item(test_db, id=30, title="Done epic with unfiled test", type="epic",
                    status="done", spec=body)
        rec = _run_hc(hc_deferred_items, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "YOK-30" in r.detail
        assert "UNFILED" in r.detail

    def test_pass_done_epic_all_filed(self, test_db):
        """Test 4: PASS for done epic with all deferred items filed."""
        body = textwrap.dedent("""\
            ## Problem
            Some problem.

            ## Deferred Items

            | Description | Reason | Ticket |
            |---|---|---|
            | Remove column | Migration risk | YOK-99 |
            | Add tests | Out of scope | YOK-100 |

            ## Shepherd Log
            Done.""")
        insert_item(test_db, id=40, title="Done epic all filed test", type="epic",
                    status="done", spec=body)
        rec = _run_hc(hc_deferred_items, test_db)
        assert "YOK-40" not in _result(rec).detail

    def test_warn_deferral_language_no_section(self, test_db):
        """Test 5: WARN for done epic with untracked deferral language."""
        body = textwrap.dedent("""\
            ## Problem
            Some problem.

            ## Requirements
            Do something.
            Column removal deferred to a follow-up item.

            ## Shepherd Log
            Done.""")
        insert_item(test_db, id=50, title="Done epic deferral language test", type="epic",
                    status="done", spec=body)
        rec = _run_hc(hc_deferred_items, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "YOK-50" in r.detail
        assert "deferral language" in r.detail

    def test_pass_deferral_language_with_sun_reference(self, test_db):
        """Test 6: PASS for deferral language with adjacent YOK-N reference."""
        body = textwrap.dedent("""\
            ## Problem
            Some problem.

            ## Requirements
            Column removal deferred to a follow-up item YOK-99.

            ## Shepherd Log
            Done.""")
        insert_item(test_db, id=60, title="Done epic deferral with ref test", type="epic",
                    status="done", spec=body)
        rec = _run_hc(hc_deferred_items, test_db)
        assert "YOK-60" not in _result(rec).detail

    def test_non_epic_done_excluded(self, test_db):
        """Test 7: Non-epic done items excluded."""
        insert_item(test_db, id=70, title="Non-epic done item test", type="issue",
                    status="done", spec="This was deferred to a follow-up item.")
        rec = _run_hc(hc_deferred_items, test_db)
        assert "YOK-70" not in _result(rec).detail

    def test_deferral_in_code_block_excluded(self, test_db):
        """Test 8: Deferral language inside code blocks excluded."""
        body = "## Problem\nSome problem.\n\n```\nThis was deferred to a follow-up item.\n```\n\n## Shepherd Log\nDone."
        insert_item(test_db, id=80, title="Done epic code block test", type="epic",
                    status="done", spec=body)
        rec = _run_hc(hc_deferred_items, test_db)
        assert "YOK-80" not in _result(rec).detail

    def test_deferred_items_warn_severity(self, test_db):
        """Test 9: HC-deferred-items issues appear as WARN severity (not FAIL)."""
        body = textwrap.dedent("""\
            ## Problem
            Something.

            ## Deferred Items

            | Description | Reason | Ticket |
            |---|---|---|
            | Remove column | Risk | UNFILED |""")
        insert_item(test_db, id=90, title="Done epic warn severity test", type="epic",
                    status="done", spec=body)
        rec = _run_hc(hc_deferred_items, test_db)
        assert _result(rec).result == "WARN"

    def test_active_epic_not_flagged(self, test_db):
        """Test 10: Active epic with deferral language not flagged (only done checked)."""
        insert_item(test_db, id=100, title="Active epic deferral test", type="epic",
                    status="implementing",
                    spec="This was deferred to a follow-up item.")
        rec = _run_hc(hc_deferred_items, test_db)
        assert "YOK-100" not in _result(rec).detail


class TestHCProjectsWithoutFlows:
    """Tests for HC-projects-without-flows."""

    def _add_project(self, conn, project_id):
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, created_at, public_item_prefix) "
            "VALUES (%s, %s, %s, %s, 'YOK') "
            "ON CONFLICT (id) DO UPDATE SET "
            "slug=EXCLUDED.slug, name=EXCLUDED.name",
            (
                _project_id(project_id),
                project_id,
                project_id,
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()

    def _add_flow(self, conn, flow_id, project_id):
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id, project_id, name, stages, created_at) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (
                flow_id,
                _project_id(project_id),
                f"flow-{flow_id}",
                "[]",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()

    def _cover_seeded_projects(self, conn):
        self._add_flow(conn, "flow-yoke", "yoke")
        self._add_flow(conn, "flow-buzz", "buzz")

    def test_pass_all_projects_have_flows(self, test_db):
        """Test 1: PASS when all projects have deployment flows."""
        self._cover_seeded_projects(test_db)
        self._add_project(test_db, "proj-a")
        self._add_flow(test_db, "flow-a", "proj-a")
        rec = _run_hc(hc_projects_without_flows, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_project_no_flows(self, test_db):
        """Test 2: WARN when a project has no deployment flows."""
        self._add_project(test_db, "proj-b")
        rec = _run_hc(hc_projects_without_flows, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "proj-b" in r.detail

    def test_warn_multiple_projects_without_flows(self, test_db):
        """Test 3: WARN lists multiple projects without flows."""
        self._add_project(test_db, "proj-c")
        self._add_project(test_db, "proj-d")
        self._add_project(test_db, "proj-e")
        self._add_flow(test_db, "flow-e", "proj-e")
        rec = _run_hc(hc_projects_without_flows, test_db)
        r = _result(rec)
        assert "proj-c" in r.detail
        assert "proj-d" in r.detail
        assert "proj-e" not in r.detail

    def test_graceful_no_deployment_flows_table(self, test_db):
        """Test 4: Graceful when deployment_flows table is missing."""
        self._add_project(test_db, "proj-f")
        test_db.execute("DROP TABLE IF EXISTS deployment_flows")
        test_db.commit()
        rec = _run_hc(hc_projects_without_flows, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "deployment_flows table" in r.detail

    def test_graceful_no_projects_table(self, test_db):
        """Test 5: Graceful when projects table is missing."""
        test_db.execute("DROP TABLE IF EXISTS deployment_flows")
        test_db.execute("DROP TABLE IF EXISTS projects CASCADE")
        test_db.commit()
        rec = _run_hc(hc_projects_without_flows, test_db)
        assert _result(rec).result == "PASS"


class TestHCIncompleteDeployStage:
    """Tests for HC-incomplete-deploy-stage."""

    def test_pass_no_done_items_with_flow(self, test_db):
        """Test 6: PASS when no done items have deployment_flow."""
        insert_item(test_db, id=10, title="Done item no flow test",
                    status="done")
        rec = _run_hc(hc_incomplete_deploy_stage, test_db)
        assert _result(rec).result == "PASS"

    def test_pass_done_item_deploy_stage_complete(self, test_db):
        """Test 7: PASS when done item has deploy_stage=complete."""
        insert_item(test_db, id=20, title="Done deployed item test",
                    status="done", deployment_flow="flow-a", deploy_stage="complete")
        rec = _run_hc(hc_incomplete_deploy_stage, test_db)
        assert _result(rec).result == "PASS"

    def test_warn_done_item_null_deploy_stage(self, test_db):
        """Test 8: WARN when done item has deployment_flow but deploy_stage is NULL."""
        insert_item(test_db, id=30, title="Done not deployed item test",
                    status="done", deployment_flow="flow-a")
        rec = _run_hc(hc_incomplete_deploy_stage, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "YOK-30" in r.detail

    def test_warn_done_item_non_complete_stage(self, test_db):
        """Test 9: WARN when done item has deploy_stage not 'complete'."""
        insert_item(test_db, id=40, title="Done partial deploy test",
                    status="done", deployment_flow="flow-b", deploy_stage="staging")
        rec = _run_hc(hc_incomplete_deploy_stage, test_db)
        r = _result(rec)
        assert r.result == "WARN"
        assert "staging" in r.detail

    def test_non_done_items_not_flagged(self, test_db):
        """Test 10: Non-done items not flagged."""
        insert_item(test_db, id=50, title="Active with flow item test",
                    status="implementing", deployment_flow="flow-a")
        rec = _run_hc(hc_incomplete_deploy_stage, test_db)
        assert _result(rec).result == "PASS"

    def test_multiple_done_items_mixed(self, test_db):
        """Test 12: Multiple done items with incomplete deploy_stage."""
        insert_item(test_db, id=70, title="Done incomplete A test item",
                    status="done", deployment_flow="flow-a")
        insert_item(test_db, id=71, title="Done incomplete B test item",
                    status="done", deployment_flow="flow-b", deploy_stage="staging")
        insert_item(test_db, id=72, title="Done complete C test item",
                    status="done", deployment_flow="flow-c", deploy_stage="complete")
        rec = _run_hc(hc_incomplete_deploy_stage, test_db)
        r = _result(rec)
        assert "YOK-70" in r.detail
        assert "YOK-71" in r.detail
        assert "YOK-72" not in r.detail
