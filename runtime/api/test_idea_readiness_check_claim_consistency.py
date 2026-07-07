"""Coverage for ``verify_file_budget_claim_consistency`` of the pre-handoff
readiness checks.

Split off from ``test_idea_readiness_check.py`` to keep each test module
within the file-line budget; behavior and test names are preserved so
verification stays grep-able.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.idea_readiness_check import (
    verify_file_budget_claim_consistency,
)


def _seed_item(conn, spec: str, item_id: int = 1) -> None:
    now = iso8601_now()
    conn.execute(
        """
        INSERT INTO items
            (id, title, type, status, priority, project_id, project_sequence,
             created_at, updated_at, source, spec)
        VALUES (%s, 'Readiness item', 'issue', 'idea', 'medium',
                1, %s, %s, %s, 'test', %s)
        """,
        (item_id, item_id, now, now, spec),
    )


def _seed_claim(conn, *, state: str = "planned", item_id: int = 1) -> None:
    conn.execute(
        """
        INSERT INTO path_claims
            (id, item_id, state, actor_id, integration_target, registered_at)
        VALUES (10, %s, %s, 4242, 'main', %s)
        """,
        (item_id, state, iso8601_now()),
    )


def _seed_claim_paths(conn, paths: list[str]) -> None:
    for target_id, path in enumerate(paths, start=1):
        conn.execute(
            """
            INSERT INTO path_targets
                (id, project_id, kind, path_string, generation, created_at)
            VALUES (%s, 1, 'file', %s, 1, %s)
            """,
            (target_id, path, iso8601_now()),
        )
        conn.execute(
            """
            INSERT INTO path_claim_targets
                (claim_id, target_id, declared_at)
            VALUES (10, %s, %s)
            """,
            (target_id, iso8601_now()),
        )


class TestVerifyFileBudgetClaimConsistency:
    @pytest.fixture
    def conn_with_claim(self, tmp_path):
        with init_test_db(tmp_path) as db_path:
            conn = connect_test_db(db_path)
            now = iso8601_now()
            conn.execute(
                """
                INSERT INTO actors (id, kind, system_component, created_at)
                VALUES (4242, 'system', 'readiness-test', %s)
                """,
                (now,),
            )
            conn.commit()
            try:
                yield conn, db_path
            finally:
                conn.close()

    def test_consistent_set_passes(self, conn_with_claim):
        conn, _ = conn_with_claim
        _seed_item(
            conn,
            "## File Budget\n\n- `runtime/api/domain/foo.py`\n"
            "- `docs/foo.md`\n",
        )
        _seed_claim(conn)
        _seed_claim_paths(conn, ["runtime/api/domain/foo.py", "docs/foo.md"])
        conn.commit()
        issues = verify_file_budget_claim_consistency(conn, 1)
        assert issues == []

    def test_file_budget_extra_path_flagged(self, conn_with_claim):
        conn, _ = conn_with_claim
        _seed_item(
            conn,
            "## File Budget\n\n- `runtime/api/domain/foo.py`\n"
            "- `runtime/api/domain/missing.py`\n",
        )
        _seed_claim(conn)
        _seed_claim_paths(conn, ["runtime/api/domain/foo.py"])
        conn.commit()
        issues = verify_file_budget_claim_consistency(conn, 1)
        assert any(i.code == "FILE_BUDGET_NOT_IN_CLAIM" for i in issues)

    def test_claim_extra_path_flagged(self, conn_with_claim):
        conn, _ = conn_with_claim
        _seed_item(conn, "## File Budget\n\n- `runtime/api/domain/foo.py`\n")
        _seed_claim(conn)
        _seed_claim_paths(
            conn,
            ["runtime/api/domain/foo.py", "runtime/api/domain/extra.py"],
        )
        conn.commit()
        issues = verify_file_budget_claim_consistency(conn, 1)
        assert any(i.code == "CLAIM_NOT_IN_FILE_BUDGET" for i in issues)

    def test_blocked_widened_claim_matches_file_budget(
        self, conn_with_claim,
    ):
        """AC-7: a blocked dependent claim with widened coverage matching
        the File Budget passes consistency even while the upstream claim is
        still non-terminal."""
        conn, _ = conn_with_claim
        _seed_item(
            conn,
            "## File Budget\n\n- `runtime/api/domain/foo.py`\n"
            "- `runtime/api/domain/bar.py`\n",
        )
        _seed_claim(conn, state="blocked")
        _seed_claim_paths(
            conn, ["runtime/api/domain/foo.py", "runtime/api/domain/bar.py"]
        )
        conn.commit()
        issues = verify_file_budget_claim_consistency(conn, 1)
        assert issues == []

    def test_paths_outside_file_budget_section_are_ignored(
        self, conn_with_claim,
    ):
        """Path mentions in Out of Scope, Simplify, or AC sections must not
        leak into File Budget claim-consistency checks."""
        conn, _ = conn_with_claim
        spec = (
            "# Title\n\n"
            "## Out of scope\n\n"
            "- Rewriting `runtime/api/domain/path_snapshots.py`.\n\n"
            "## File Budget\n\n"
            "- `runtime/api/domain/foo.py`\n\n"
            "## Acceptance Criteria\n\n"
            "- AC-1: see `docs/some-other.md` for context.\n"
        )
        _seed_item(conn, spec)
        _seed_claim(conn)
        _seed_claim_paths(conn, ["runtime/api/domain/foo.py"])
        conn.commit()
        issues = verify_file_budget_claim_consistency(conn, 1)
        assert issues == []
