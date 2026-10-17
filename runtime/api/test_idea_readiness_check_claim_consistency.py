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
    verify_effective_file_budget_claim_consistency,
    verify_file_budget_claim_consistency,
)


def _seed_item(conn, spec: str, item_id: int = 1) -> None:
    now = iso8601_now()
    conn.execute(
        """
        INSERT INTO items
            (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
             created_at, updated_at, source, spec)
        VALUES (%s, 'Readiness item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'medium',
                1, %s, %s, %s, 'test', %s)
        """,
        (item_id, item_id, now, now, spec),
    )


def _seed_claim(conn, *, state: str = "planned", item_id: int = 1) -> None:
    conn.execute(
        """
        INSERT INTO path_claims
            (id, owner_kind, owner_item_id, state, integration_target, registered_at)
        VALUES (10, 'item', %s, %s, 'main', %s)
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
            "## File Budget\n\n- `runtime/api/domain/foo.py`\n- `docs/foo.md`\n",
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
        self,
        conn_with_claim,
    ):
        """A blocked dependent claim with widened coverage matching
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
        self,
        conn_with_claim,
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


def test_pre_task_epic_defers_readiness_claim_parity(test_db):
    from runtime.api.domain.path_claim_task_test_support import seed_epic
    from yoke_core.domain.path_claim_required_gate import evaluate

    item_id = seed_epic(test_db, item_id=22001, status="plan-drafted")
    test_db.execute(
        "UPDATE items SET spec = %s WHERE id = %s",
        ("## File Budget\n\n- `src/future.py`\n", item_id),
    )
    test_db.commit()

    assert evaluate(test_db, item_id)["verdict"] == "pass"
    assert verify_effective_file_budget_claim_consistency(test_db, item_id) == []


def test_epic_readiness_reports_only_uncovered_task_paths(test_db, tmp_path):
    from runtime.api.domain.path_claim_task_test_support import (
        bind_claim,
        seed_epic,
        seed_item_claim,
        seed_target,
        seed_worker_task,
    )
    from runtime.api.task_files_touched_test_support import declare_task_files
    from yoke_core.domain.path_claim_task_coverage import evaluate_task_coverage

    item_id = seed_epic(test_db, item_id=22002)
    test_db.execute(
        "UPDATE items SET spec = %s WHERE id = %s",
        ("## File Budget\n\n- `src/parent-only.py`\n", item_id),
    )
    for task_num, path in enumerate(("src/covered.py", "src/missing.py"), 1):
        seed_worker_task(
            test_db,
            item_id=item_id,
            task_num=task_num,
            lane_path=tmp_path / str(task_num),
            budget_path=path,
        )
    declare_task_files(test_db, item_id, 1, ["src/covered.py", "src/partial.py"])
    target = seed_target(test_db, item_id=item_id, path="src/covered.py")
    claim = seed_item_claim(test_db, item_id=item_id, target_ids=(target,))
    bind_claim(test_db, claim_id=claim, item_id=item_id, task_num=1)
    # An unbound whole-item claim cannot replace the missing task claim.
    missing = seed_target(test_db, item_id=item_id, path="src/missing.py")
    seed_item_claim(test_db, item_id=item_id, target_ids=(missing,))

    coverage = evaluate_task_coverage(test_db, item_id)
    issues = verify_effective_file_budget_claim_consistency(test_db, item_id)

    assert coverage.missing_tasks == (2,)
    assert coverage.partial_tasks == (1,)
    assert [issue.context["path"] for issue in issues] == list(coverage.uncovered_paths)
    assert {issue.context["path"] for issue in issues} == {
        "src/missing.py",
        "src/partial.py",
    }
    assert all(issue.code == "FILE_BUDGET_NOT_IN_CLAIM" for issue in issues)
    assert all("--task-num" in issue.remediation for issue in issues)
