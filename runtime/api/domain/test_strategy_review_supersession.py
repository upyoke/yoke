"""A new strategy revision releases the review the previous one asked for."""

from __future__ import annotations

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.domain.decision_request_disposition import (
    dispose_ended_decision_requests,
)
from yoke_core.domain.strategy_review_requests import (
    ensure_strategy_revision_review,
)


def _strategy_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE strategy_docs (
            project_id INTEGER NOT NULL,
            slug TEXT NOT NULL,
            archived_at TEXT,
            PRIMARY KEY (project_id, slug)
        );
        CREATE TABLE strategy_doc_revisions (
            project_id INTEGER NOT NULL,
            slug TEXT NOT NULL,
            revision INTEGER NOT NULL,
            PRIMARY KEY (project_id, slug, revision)
        );
        """
    )
    conn.execute("INSERT INTO strategy_docs VALUES (10, 'CURRENT-PLAN', NULL)")


def _statuses(conn, slug: str) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT subject_key, status FROM decision_requests "
            "WHERE kind = 'strategy_revision_review' ORDER BY id"
        ).fetchall()
        if str(row[0]).split(":")[1] == slug
    }


def test_a_new_revision_withdraws_the_review_it_superseded() -> None:
    with decision_request_connection() as conn:
        _strategy_tables(conn)
        for revision in (1, 2):
            conn.execute(
                "INSERT INTO strategy_doc_revisions VALUES (10, 'CURRENT-PLAN', ?)",
                (revision,),
            )
            ensure_strategy_revision_review(
                conn,
                project_id=10,
                slug="CURRENT-PLAN",
                revision=revision,
                originator_actor_id=2,
            )
        conn.commit()

        statuses = _statuses(conn, "CURRENT-PLAN")
        assert statuses["10:CURRENT-PLAN:1"] == "withdrawn"
        assert statuses["10:CURRENT-PLAN:2"] == "pending"


def test_the_sweep_converges_reviews_superseded_before_the_rule_existed() -> None:
    with decision_request_connection() as conn:
        _strategy_tables(conn)
        for revision in (1, 2, 3):
            conn.execute(
                "INSERT INTO strategy_doc_revisions VALUES (10, 'CURRENT-PLAN', ?)",
                (revision,),
            )
        for revision in (1, 2, 3):
            ensure_strategy_revision_review(
                conn,
                project_id=10,
                slug="CURRENT-PLAN",
                revision=revision,
                originator_actor_id=2,
            )
        conn.execute(
            "UPDATE decision_requests SET status='pending', "
            "withdrawal_reason=NULL, withdrawn_at=NULL"
        )
        conn.commit()

        result = dispose_ended_decision_requests(conn)

        statuses = _statuses(conn, "CURRENT-PLAN")
        assert statuses["10:CURRENT-PLAN:1"] == "withdrawn"
        assert statuses["10:CURRENT-PLAN:2"] == "withdrawn"
        assert statuses["10:CURRENT-PLAN:3"] == "pending"
        assert result["withdrawn_count"] == 2
        assert result["retained_count"] == 1
