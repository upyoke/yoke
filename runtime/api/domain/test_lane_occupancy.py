"""Tests for refusing a write into a lane another session holds.

The defect these cover is not that the guard decided wrongly — it is
that the guard never reached a decision. Two mechanisms compounded:
lane paths were resolved through the evaluating machine's checkout map,
which a relayed evaluation does not have, and a caller whose claims
therefore resolved to nothing was allowed unconditionally.

So the coverage here deliberately exercises the *unmapped* case
(:class:`TestResolutionWithoutCheckoutMapping`) as well as the
ownership decision itself, because a test that registers a machine
checkout reproduces the one environment where the old code worked.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_session_cwd
from yoke_core.domain.lane_occupancy import occupying_claim
from yoke_core.domain.lint_session_cwd_validate import (
    FOREIGN_LANE_FAILURE_CLASS,
)
from yoke_core.domain.session_claimed_worktrees import claimed_worktrees
from yoke_core.domain.work_claim_targets import make_item_target

HOLDER = "sid-holder"
INTRUDER = "sid-intruder"
HELD_ITEM = 4101
OTHER_ITEM = 4102


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _held_lane(conn, repo):
    """One item whose lane is claimed by ``HOLDER``. No checkout is
    registered anywhere in this module on purpose."""
    seed_item(conn, item_id=HELD_ITEM, branch="held-lane", repo_path=repo)
    seed_item_claim(conn, HOLDER, item_id=HELD_ITEM)
    lane = repo / ".worktrees" / "held-lane"
    lane.mkdir(parents=True, exist_ok=True)
    return lane


class TestResolutionWithoutCheckoutMapping:
    """Lane authority resolves from recorded rows alone.

    A relayed hook evaluation runs on a server that holds no checkout of
    the caller's repository, so any resolution routed through a
    checkout mapping yields nothing and silently drops every claim.
    """

    def test_claimed_lane_resolves_with_no_machine_checkout(self, conn, repo):
        lane = _held_lane(conn, repo)
        claims = claimed_worktrees(conn, session_id=HOLDER)
        assert [c.worktree_path for c in claims] == [str(lane)]

    def test_released_lane_contributes_no_authority(self, conn, repo):
        _held_lane(conn, repo)
        conn.execute(
            "UPDATE item_worktrees SET released_at = '2026-01-01T00:00:00Z' "
            "WHERE item_id = %s",
            (HELD_ITEM,),
        )
        conn.commit()
        assert claimed_worktrees(conn, session_id=HOLDER) == []


class TestOccupancy:
    def test_foreign_live_claim_is_reported(self, conn, repo):
        lane = _held_lane(conn, repo)
        found = occupying_claim(
            conn,
            target=str(lane / "src" / "a.py"),
            session_id=INTRUDER,
        )
        assert found is not None
        assert found.session_id == HOLDER
        assert found.item_id == HELD_ITEM
        assert found.lane_path == str(lane)

    def test_own_lane_is_not_an_occupant(self, conn, repo):
        lane = _held_lane(conn, repo)
        assert (
            occupying_claim(
                conn,
                target=str(lane / "a.py"),
                session_id=HOLDER,
            )
            is None
        )

    def test_lane_without_live_claim_is_not_an_occupant(self, conn, repo):
        lane = _held_lane(conn, repo)
        target = make_item_target(HELD_ITEM)
        conn.execute(
            "UPDATE work_claims SET released_at = '2026-01-01T00:00:00Z' "
            "WHERE target_kind = %s AND scope = %s",
            (target.kind, target.scope_json()),
        )
        conn.commit()
        assert (
            occupying_claim(
                conn,
                target=str(lane / "a.py"),
                session_id=INTRUDER,
            )
            is None
        )

    def test_path_outside_every_lane_is_not_an_occupant(self, conn, repo):
        _held_lane(conn, repo)
        assert (
            occupying_claim(
                conn,
                target=str(repo / "runtime" / "api" / "a.py"),
                session_id=INTRUDER,
            )
            is None
        )


class TestForeignLaneDenial:
    """Every caller state, because the damaging one holds no claim."""

    def _write_into_held_lane(self, conn, repo, session_id):
        lane = _held_lane(conn, repo)
        return lint_session_cwd.evaluate_pre_tool_use(
            {
                "session_id": session_id,
                "tool_name": "Write",
                "tool_input": {"file_path": str(lane / "src" / "a.py")},
            }
        )

    def test_caller_with_no_claims_is_denied(self, conn, repo):
        verdict = self._write_into_held_lane(conn, repo, INTRUDER)
        assert verdict.allow is False
        assert verdict.failure_class == FOREIGN_LANE_FAILURE_CLASS

    def test_caller_claiming_another_item_with_a_lane_is_denied(
        self,
        conn,
        repo,
    ):
        seed_item(
            conn,
            item_id=OTHER_ITEM,
            branch="other-lane",
            repo_path=repo,
        )
        seed_item_claim(conn, INTRUDER, item_id=OTHER_ITEM)
        (repo / ".worktrees" / "other-lane").mkdir(parents=True)
        verdict = self._write_into_held_lane(conn, repo, INTRUDER)
        assert verdict.allow is False
        assert verdict.failure_class == FOREIGN_LANE_FAILURE_CLASS

    def test_caller_claiming_another_item_without_a_lane_is_denied(
        self,
        conn,
        repo,
    ):
        seed_item(conn, item_id=OTHER_ITEM, branch=None)
        seed_item_claim(conn, INTRUDER, item_id=OTHER_ITEM)
        verdict = self._write_into_held_lane(conn, repo, INTRUDER)
        assert verdict.allow is False
        assert verdict.failure_class == FOREIGN_LANE_FAILURE_CLASS

    def test_holder_writing_its_own_lane_is_allowed(self, conn, repo):
        verdict = self._write_into_held_lane(conn, repo, HOLDER)
        assert verdict.allow is True

    def test_denial_names_holder_item_and_recovery(self, conn, repo):
        verdict = self._write_into_held_lane(conn, repo, INTRUDER)
        assert HOLDER in verdict.reason
        assert "yoke claims work acquire" in verdict.reason
        # The single-author remedy is wrong advice across sessions: it
        # would commit on top of the holder's uncommitted work.
        assert "stash" not in verdict.reason.lower()
