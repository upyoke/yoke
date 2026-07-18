# ruff: noqa: F811
"""Query/listing tests for yoke_core.domain.deployment_runs.
Covers cmd_list, cmd_items, cmd_find_by_item, cmd_lineage*, cmd_qa_*.

Split from ``test_deployment_runs_full.py``.
"""

from __future__ import annotations

from yoke_core.domain import deployment_runs as dr
from runtime.api.test_deployment_runs_full_helpers import db_path  # noqa: F401


class TestList:
    """cmd_list with project/status filters."""

    def test_list_all(self, db_path):
        dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        result = dr.cmd_list(db_path=db_path)
        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 2

    def test_list_by_project(self, db_path):
        dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_create_run("externalwebapp", "externalwebapp-standard", db_path=db_path)
        result = dr.cmd_list(project="externalwebapp", db_path=db_path)
        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 1

    def test_list_by_status(self, db_path):
        r1 = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_update(r1, "status", "executing", db_path=db_path)
        result = dr.cmd_list(status="created", db_path=db_path)
        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 1

    def test_list_empty(self, db_path):
        result = dr.cmd_list(db_path=db_path)
        assert result == ""


class TestItems:
    """cmd_items: list items in a run."""

    def test_items_empty(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        result = dr.cmd_items(rid, db_path=db_path)
        assert result == ""

    def test_items_ordered(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_add_item(rid, 200, db_path=db_path)
        dr.cmd_add_item(rid, 100, db_path=db_path)
        result = dr.cmd_items(rid, db_path=db_path)
        lines = result.strip().split("\n")
        # Ordered by item_id ASC
        assert "100" in lines[0]
        assert "200" in lines[1]


class TestFindByItem:
    """cmd_find_by_item: find run(s) for an item."""

    def test_find_by_item(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_add_item(rid, 42, db_path=db_path)
        result = dr.cmd_find_by_item(42, db_path=db_path)
        assert rid in result

    def test_find_by_item_with_status(self, db_path):
        r1 = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        r2 = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_add_item(r1, 42, db_path=db_path)
        dr.cmd_add_item(r2, 42, db_path=db_path)
        dr.cmd_update(r1, "status", "executing", db_path=db_path)
        result = dr.cmd_find_by_item(42, status="created", db_path=db_path)
        assert r2 in result
        assert r1 not in result

    def test_find_by_item_not_found(self, db_path):
        result = dr.cmd_find_by_item(999, db_path=db_path)
        assert result == ""


class TestLineage:
    """cmd_lineage, cmd_lineage_create, cmd_lineage_final_status."""

    def test_lineage_returns_related_runs(self, db_path):
        r1 = dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-001", db_path=db_path,
        )
        dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-001", db_path=db_path,
        )
        result = dr.cmd_lineage(r1, db_path=db_path)
        assert result is not None
        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 2

    def test_lineage_no_lineage_returns_none(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        result = dr.cmd_lineage(rid, db_path=db_path)
        assert result is None

    def test_lineage_create(self, db_path):
        lid = dr.cmd_lineage_create(db_path=db_path)
        assert lid.startswith("lineage-")
        assert lid.endswith("-001")

    def test_lineage_final_status(self, db_path):
        dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-final",
            target_env="production",
            db_path=db_path,
        )
        status = dr.cmd_lineage_final_status("rel-final", db_path=db_path)
        assert status == "created"

    def test_lineage_final_status_none(self, db_path):
        status = dr.cmd_lineage_final_status("nonexistent", db_path=db_path)
        assert status == "none"

    def test_lineage_final_status_succeeded(self, db_path):
        rid = dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-succ",
            target_env="production",
            db_path=db_path,
        )
        dr.cmd_update(rid, "status", "succeeded", db_path=db_path)
        status = dr.cmd_lineage_final_status("rel-succ", db_path=db_path)
        assert status == "succeeded"


class TestQA:
    """cmd_qa_add, cmd_qa_list, cmd_qa_update."""

    def test_qa_add_and_list(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_qa_add(rid, "smoke-test", "flow_default", 1, db_path=db_path)
        dr.cmd_qa_add(rid, "integration", "flow_default", 0, db_path=db_path)

        result = dr.cmd_qa_list(rid, db_path=db_path)
        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 2

    def test_qa_update(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_qa_add(rid, "smoke-test", "flow_default", 1, db_path=db_path)

        err = dr.cmd_qa_update(rid, "smoke-test", "passed", db_path=db_path)
        assert err is None

        result = dr.cmd_qa_list(rid, db_path=db_path)
        assert "passed" in result

    def test_qa_update_invalid_status(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_qa_add(rid, "smoke-test", "flow_default", 1, db_path=db_path)
        err = dr.cmd_qa_update(rid, "smoke-test", "bogus", db_path=db_path)
        assert err is not None
        assert "invalid QA status" in err

    def test_qa_list_empty(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        result = dr.cmd_qa_list(rid, db_path=db_path)
        assert result == ""
