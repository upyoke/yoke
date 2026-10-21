"""Tests for the worktree-status pre-commit invariant.

Covers the branches of evaluate():
- branch naming no item lane (main, unknown PREFIX-N) -> skipped, ok=True
- item branch + status in allowed set -> ok=True
- item branch + status NOT in allowed set -> ok=False with message
- DB unreachable → skipped, ok=True (fail-open on env issues)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.lane_ref_test_support import (
    BUZZ_PROJECT_ID,
    seed_buzz_project,
    seed_item,
)
from yoke_core.domain.check_worktree_status_invariant import (
    ALLOWED_IMPLEMENTATION_STATUSES,
    WorktreeStatusVerdict,
    evaluate,
)

# Each lane sequence N is also the items.id of a decoy whose status gives
# the opposite verdict, so reading the number as items.id fails the test.
YOKE_ITEMS = [
    (600, 60, "implementing"),
    (700, 70, "refined-idea"),
    (701, 71, "reviewing-implementation"),
    (702, 72, "polishing-implementation"),
    (703, 73, "done"),
    (60, 9060, "done"),
    (70, 9070, "implementing"),
    (71, 9071, "done"),
    (72, 9072, "done"),
    (73, 9073, "implementing"),
]
BUZZ_ITEMS = [
    (800, 60, "refined-idea"),
    (801, 61, "implementing"),
    (61, 9061, "done"),
]


@pytest.fixture
def seeded_db(tmp_path):
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            seed_buzz_project(conn)
            for item_id, sequence, status in YOKE_ITEMS:
                seed_item(
                    conn, item_id, project_id=1, sequence=sequence, status=status,
                )
            for item_id, sequence, status in BUZZ_ITEMS:
                seed_item(
                    conn,
                    item_id,
                    project_id=BUZZ_PROJECT_ID,
                    sequence=sequence,
                    status=status,
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
        assert "names no item lane" in result.skip_reason

    def test_implementing_passes(self, seeded_db):
        result = _patched_evaluate(branch="YOK-60", db_path=seeded_db)
        assert result.ok is True
        assert result.skipped is False
        assert result.observed_status == "implementing"
        assert result.message == ""

    def test_reviewing_implementation_passes(self, seeded_db):
        result = _patched_evaluate(branch="YOK-71", db_path=seeded_db)
        assert result.ok is True
        assert result.observed_status == "reviewing-implementation"

    def test_polishing_implementation_passes(self, seeded_db):
        result = _patched_evaluate(branch="YOK-72", db_path=seeded_db)
        assert result.ok is True
        assert result.observed_status == "polishing-implementation"

    def test_refined_idea_blocks_with_remediation(self, seeded_db):
        result = _patched_evaluate(branch="YOK-70", db_path=seeded_db)
        assert result.ok is False
        assert result.observed_status == "refined-idea"
        assert result.item_id == 700
        # Block message names the status, the allowed set, and the fix.
        assert "refined-idea" in result.message
        assert "implementing" in result.message
        assert "/yoke implement YOK-70" in result.message
        assert "--no-verify" not in result.message

    def test_done_blocks(self, seeded_db):
        # Past polishing-implementation — implementation phase is over.
        result = _patched_evaluate(branch="YOK-73", db_path=seeded_db)
        assert result.ok is False
        assert result.observed_status == "done"

    def test_missing_item_row_is_skipped(self, seeded_db):
        result = _patched_evaluate(branch="YOK-99999", db_path=seeded_db)
        assert result.ok is True
        assert result.skipped is True
        assert "names no item lane" in result.skip_reason
        assert result.item_id is None

    def test_other_project_lane_resolves_its_own_item(self, seeded_db):
        blocked = _patched_evaluate(branch="BUZ-60", db_path=seeded_db)
        assert blocked.ok is False
        assert blocked.item_id == 800
        assert "/yoke implement BUZ-60" in blocked.message
        passed = _patched_evaluate(branch="BUZ-61", db_path=seeded_db)
        assert passed.ok is True
        assert passed.item_id == 801

    def test_trial_ref_is_skipped(self, seeded_db):
        result = _patched_evaluate(branch="trial/YOK-70", db_path=seeded_db)
        assert result.ok is True
        assert result.skipped is True

    def test_db_unreachable_is_skipped(self, tmp_path):
        with patch(
            "yoke_core.domain.check_worktree_status_invariant."
            "db_helpers.connect",
            side_effect=RuntimeError("Postgres authority not reachable"),
        ):
            result = _patched_evaluate(
                branch="YOK-60",
                db_path=str(tmp_path / "does-not-exist.db"),
            )
        assert result.ok is True
        assert result.skipped is True

    def test_db_path_resolver_returns_none_skips(self, seeded_db):
        with patch(
            "yoke_core.domain.check_worktree_status_invariant._resolve_db_path_or_none",
            return_value=None,
        ):
            result = evaluate(branch="YOK-60")
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
