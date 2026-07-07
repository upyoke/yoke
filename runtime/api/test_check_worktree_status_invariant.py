"""Tests for the worktree-status pre-commit invariant.

Covers the five branches of evaluate():
- non-item branch -> skipped, ok=True
- item branch with no items row -> skipped, ok=True
- item branch + status in allowed set -> ok=True
- item branch + status NOT in allowed set -> ok=False with message
- DB unreachable → skipped, ok=True (fail-open on env issues)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.check_worktree_status_invariant import (
    ALLOWED_IMPLEMENTATION_STATUSES,
    WorktreeStatusVerdict,
    evaluate,
)
from yoke_core.domain.db_helpers import iso8601_now


def _item_branch(item_id: int) -> str:
    return f"YOK-{item_id}"


@pytest.fixture
def seeded_db(tmp_path):
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        now = iso8601_now()
        try:
            rows = [
                (600, "Implementing", "implementing", now, now),
                (700, "Refined idea", "refined-idea", now, now),
                (701, "Reviewing implementation", "reviewing-implementation", now, now),
                (702, "Polishing implementation", "polishing-implementation", now, now),
                (703, "Done", "done", now, now),
            ]
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO items
                        (id, title, type, status, priority, project_id,
                         project_sequence, created_at, updated_at, source)
                    VALUES (%s, %s, 'issue', %s, 'medium', 1, %s, %s, %s, 'test')
                    """,
                    (row[0], row[1], row[2], row[0], row[3], row[4]),
                )
            conn.commit()
        finally:
            conn.close()
        yield db_path


def _patched_evaluate(*, branch, db_path):
    """Run evaluate() with a patched DB path resolver."""
    with patch(
        "yoke_core.domain.check_worktree_status_invariant._resolve_db_path_or_none",
        return_value=db_path,
    ):
        return evaluate(branch=branch)


class TestEvaluate:
    def test_non_item_branch_is_skipped(self, seeded_db):
        result = _patched_evaluate(branch="main", db_path=seeded_db)
        assert isinstance(result, WorktreeStatusVerdict)
        assert result.ok is True
        assert result.skipped is True
        assert "not a YOK-N" in result.skip_reason

    def test_implementing_passes(self, seeded_db):
        result = _patched_evaluate(branch=_item_branch(600), db_path=seeded_db)
        assert result.ok is True
        assert result.skipped is False
        assert result.observed_status == "implementing"
        assert result.message == ""

    def test_reviewing_implementation_passes(self, seeded_db):
        result = _patched_evaluate(branch=_item_branch(701), db_path=seeded_db)
        assert result.ok is True
        assert result.observed_status == "reviewing-implementation"

    def test_polishing_implementation_passes(self, seeded_db):
        result = _patched_evaluate(branch=_item_branch(702), db_path=seeded_db)
        assert result.ok is True
        assert result.observed_status == "polishing-implementation"

    def test_refined_idea_blocks_with_remediation(self, seeded_db):
        result = _patched_evaluate(branch=_item_branch(700), db_path=seeded_db)
        assert result.ok is False
        assert result.observed_status == "refined-idea"
        assert result.item_id == 700
        # Block message names the status, the allowed set, and the fix.
        assert "refined-idea" in result.message
        assert "implementing" in result.message
        assert f"/yoke advance {_item_branch(700)}" in result.message
        assert "--no-verify" in result.message

    def test_done_blocks(self, seeded_db):
        # Past polishing-implementation — implementation phase is over.
        result = _patched_evaluate(branch=_item_branch(703), db_path=seeded_db)
        assert result.ok is False
        assert result.observed_status == "done"

    def test_missing_item_row_is_skipped(self, seeded_db):
        result = _patched_evaluate(branch=_item_branch(99999), db_path=seeded_db)
        assert result.ok is True
        assert result.skipped is True
        assert "no items row" in result.skip_reason
        assert result.item_id == 99999

    def test_db_unreachable_is_skipped(self, tmp_path):
        with patch(
            "yoke_core.domain.check_worktree_status_invariant."
            "db_helpers.connect",
            side_effect=RuntimeError("Postgres authority not reachable"),
        ):
            result = _patched_evaluate(
                branch=_item_branch(600),
                db_path=str(tmp_path / "does-not-exist.db"),
            )
        assert result.ok is True
        assert result.skipped is True

    def test_db_path_resolver_returns_none_skips(self, seeded_db):
        with patch(
            "yoke_core.domain.check_worktree_status_invariant._resolve_db_path_or_none",
            return_value=None,
        ):
            result = evaluate(branch=_item_branch(600))
        assert result.ok is True
        assert result.skipped is True
        assert "DB path not resolvable" in result.skip_reason

    def test_branch_is_none_skips(self, seeded_db):
        with patch(
            "yoke_core.domain.check_worktree_status_invariant._current_branch",
            return_value=None,
        ):
            result = evaluate()
        assert result.ok is True
        assert result.skipped is True
        assert "detached HEAD" in result.skip_reason


class TestAllowedSetMembership:
    def test_contains_three_implementation_phase_statuses(self):
        assert ALLOWED_IMPLEMENTATION_STATUSES == frozenset({
            "implementing",
            "reviewing-implementation",
            "polishing-implementation",
        })
