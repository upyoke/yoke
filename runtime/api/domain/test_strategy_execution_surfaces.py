"""Document-history, ancestry, and Blitz execution-claim contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.strategy_execution_test_support import (
    seed_strategy_doc as _seed_doc,
    strategy_test_database,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import strategy_docs, strategy_docs_ingest
from yoke_core.domain.strategy_doc_history import (
    diff_doc_revisions,
    list_doc_revisions,
    restore_doc_revision,
)
from yoke_core.domain.strategy_doc_surfaces import (
    get_strategy_surface,
    list_strategy_surfaces,
    set_strategy_doc_parent,
)
from yoke_core.domain.strategy_execution import StrategyExecutionLinkError


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with strategy_test_database(tmp_path, monkeypatch) as db_path:
        yield db_path


def test_history_diff_and_restore_append_new_revision(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        created = _seed_doc(conn, "EXECUTION-PLAN", "# Plan\n\nfirst\n")
        second = strategy_docs.replace_doc(
            conn,
            1,
            "EXECUTION-PLAN",
            "# Plan\n\nfirst\nsecond\n",
            actor_id=2,
            base_updated_at=created["updated_at"],
        )
        comparison = diff_doc_revisions(conn, 1, "EXECUTION-PLAN", 1, 2)
        restored = restore_doc_revision(
            conn,
            1,
            "EXECUTION-PLAN",
            1,
            base_updated_at=second["updated_at"],
            actor_id=3,
        )
        revisions = list_doc_revisions(conn, 1, "EXECUTION-PLAN")
        current = strategy_docs.get_doc(conn, 1, "EXECUTION-PLAN")
    finally:
        conn.close()

    assert comparison["added_lines"] == 1
    assert "+second" in comparison["diff"]
    assert restored["revision"] == 3
    assert [row["revision"] for row in revisions] == [3, 2, 1]
    assert [row["line_count"] for row in revisions] == [3, 4, 3]
    assert revisions[0]["source_operation"] == "restore:1"
    assert current["content"] == "# Plan\n\nfirst\n"


def test_history_describes_title_only_create_and_full_plan_ingest(
    tmp_db: str,
    tmp_path: Path,
) -> None:
    title = "# WORKFLOW-TYPES"
    implementation_plan = (
        f"{title}\n\n"
        "## Purpose\n\nBuild the workflow registry.\n\n"
        "## Decisions\n\nKeep one authority.\n"
    )
    conn = connect_test_db(tmp_db)
    try:
        created = _seed_doc(conn, "WORKFLOW-TYPES", title)
        plan = strategy_docs_ingest.IngestDocPlan(
            slug="WORKFLOW-TYPES",
            path=tmp_path / "WORKFLOW-TYPES.md",
            base_updated_at=created["updated_at"],
            db_updated_at=created["updated_at"],
            file_body=implementation_plan,
            changed=True,
            old_lines=1,
            new_lines=len(implementation_plan.splitlines()),
            old_bytes=len(title.encode("utf-8")),
            new_bytes=len(implementation_plan.encode("utf-8")),
        )
        strategy_docs_ingest.execute_ingest(
            conn,
            [plan],
            project_id=1,
            actor_id=2,
            session_id="strategy-author",
        )
        revisions = list_doc_revisions(conn, 1, "WORKFLOW-TYPES")
    finally:
        conn.close()

    assert revisions[0]["operation_label"] == "ingested"
    assert revisions[0]["change_summary"] == ("Full implementation plan ingested")
    assert revisions[0]["byte_length"] == len(implementation_plan.encode("utf-8"))
    assert revisions[1]["operation_label"] == "created"
    assert revisions[1]["change_summary"] == "Initial title only"
    assert revisions[1]["byte_length"] == 16


def test_single_parent_rejects_cycles_and_surfaces_ancestry(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, "PARENT", "# Parent\n")
        _seed_doc(conn, "CHILD", "# Child\n\nPARENT is the plan of record.\n")
        set_strategy_doc_parent(
            conn,
            project_id=1,
            slug="CHILD",
            parent_slug="PARENT",
        )
        detail = get_strategy_surface(conn, 1, "CHILD")
        corpus = list_strategy_surfaces(conn, 1)
        with pytest.raises(StrategyExecutionLinkError, match="cycle"):
            set_strategy_doc_parent(
                conn,
                project_id=1,
                slug="PARENT",
                parent_slug="CHILD",
            )
    finally:
        conn.close()

    assert detail["parent_slug"] == "PARENT"
    assert detail["references"] == ["PARENT"]
    child = next(row for row in corpus if row["slug"] == "CHILD")
    assert child["parent_slug"] == "PARENT"
    assert child["revisions"] == 1
    assert child["recent_writes"] == 1
