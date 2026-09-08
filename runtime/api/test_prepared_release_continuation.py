# ruff: noqa: F811
"""A release prepared before its pair merged, carried across that merge.

The scenario under test is a product change that breaks its consumer. The
producer and the consumer merge separately, and the release must go out only
once BOTH have landed — continuing on the producer's own merge publishes a
product whose consumer is still the old one, which is the failure the
prepared run exists to prevent.

The pairing is an ``item_dependencies`` row with ``gate_point='integration'``
and ``satisfaction='fact:merged'``; these tests drive that row rather than
any new state, and they assert on the two things that must not drift: which
merge is allowed to move the release, and when the lineage may be written.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain import deployment_runs_crud_mutate as mutate
from yoke_core.domain.deployment_run_lineage_rebind import (
    lineage_of,
    refuse_lineage_write,
)
from yoke_core.domain.deployment_run_pair_obligations import (
    prepared_runs_awaiting_item,
    split_pending_pair_merges,
    split_runs_by_target_environment,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from runtime.api.test_deployment_runs_full_helpers import (  # noqa: F401
    _conn,
    _insert_delivery_ready_item,
    db_path,
)


PRODUCER_ITEM = 9101
CONSUMER_ITEM = 9102
#: The fixture seeds exactly one environment for this project.
PROD_ENVIRONMENT_ID = 201
STAGE_ENVIRONMENT_ID = 204
MERGE_COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


def _pair_edge(db_path: str, dependent: int, blocker: int) -> None:
    """Record the delivery-waits-for-that-merge edge the runtime reads."""
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO item_dependencies ("
            "dependent_item_id, blocking_item_id, gate_point, satisfaction, "
            "source, rationale, created_at"
            ") VALUES (%s, %s, 'integration', 'fact:merged', 'operator', "
            "'breaking contract pair', '2026-07-28T00:00:00Z')",
            (dependent, blocker),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_merged(db_path: str, item_id: int) -> None:
    conn = _conn(db_path)
    try:
        conn.execute(
            "UPDATE items SET merged_at='2026-07-28T01:00:00Z' WHERE id=%s",
            (item_id,),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def prepared_run(db_path):
    """A run prepared for the producer while the consumer has not merged."""
    _insert_delivery_ready_item(db_path, PRODUCER_ITEM)
    _insert_delivery_ready_item(db_path, CONSUMER_ITEM)
    _pair_edge(db_path, PRODUCER_ITEM, CONSUMER_ITEM)
    run_id = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    mutate.cmd_add_item(run_id, PRODUCER_ITEM, db_path=db_path)
    return run_id


class TestPreparingBeforeThePairLands:
    def test_composition_refuses_while_the_consumer_is_unmerged(
        self, db_path, prepared_run
    ):
        ok, message = cmd_validate_composition(prepared_run, db_path)
        assert ok is False
        assert "Unsatisfied hard-block dependencies" in message

    def test_preparation_tolerates_exactly_that_pending_merge(
        self, db_path, prepared_run
    ):
        ok, _message = cmd_validate_composition(
            prepared_run, db_path, allow_pending_pair_merges=True
        )
        assert ok is True

    def test_the_pending_partner_is_named_not_merely_counted(
        self, db_path, prepared_run
    ):
        conn = _conn(db_path)
        try:
            pending, fatal = split_pending_pair_merges(conn, [PRODUCER_ITEM])
        finally:
            conn.close()
        assert fatal == []
        assert [p.blocking_item_id for p in pending] == [CONSUMER_ITEM]

    def test_prepared_run_carries_no_lineage(self, db_path, prepared_run):
        conn = _conn(db_path)
        try:
            assert lineage_of(conn, prepared_run) == ""
        finally:
            conn.close()


class TestWhichMergeAdvancesTheRelease:
    def test_the_consumer_merge_reaches_the_producers_run(
        self, db_path, prepared_run
    ):
        """The cross-item merge is what completes the pair, so it must see it."""
        conn = _conn(db_path)
        try:
            assert prepared_runs_awaiting_item(conn, CONSUMER_ITEM) == [
                prepared_run
            ]
        finally:
            conn.close()

    def test_the_producer_merge_reaches_its_own_run(self, db_path, prepared_run):
        conn = _conn(db_path)
        try:
            assert prepared_runs_awaiting_item(conn, PRODUCER_ITEM) == [
                prepared_run
            ]
        finally:
            conn.close()

    def test_an_unrelated_merge_reaches_nothing(self, db_path, prepared_run):
        _insert_delivery_ready_item(db_path, 9103)
        conn = _conn(db_path)
        try:
            assert prepared_runs_awaiting_item(conn, 9103) == []
        finally:
            conn.close()

    def test_an_executing_run_is_no_longer_awaiting_a_merge(
        self, db_path, prepared_run
    ):
        assert mutate.cmd_update(
            prepared_run, "status", "executing", db_path=db_path
        ) is None
        conn = _conn(db_path)
        try:
            assert prepared_runs_awaiting_item(conn, CONSUMER_ITEM) == []
        finally:
            conn.close()


class TestCompositionAfterTheLastMerge:
    def test_composition_passes_once_the_consumer_has_merged(
        self, db_path, prepared_run
    ):
        _mark_merged(db_path, CONSUMER_ITEM)
        ok, message = cmd_validate_composition(prepared_run, db_path)
        assert ok is True, message


class TestTheLineageWriteWindow:
    def test_an_unbound_prepared_run_accepts_the_merge_commit(
        self, db_path, prepared_run
    ):
        conn = _conn(db_path)
        try:
            assert refuse_lineage_write(conn, prepared_run, MERGE_COMMIT) is None
        finally:
            conn.close()

    def test_rebinding_the_same_commit_is_a_no_op_not_a_conflict(
        self, db_path, prepared_run
    ):
        """An interrupted close-out re-runs; it must find agreement, not an error."""
        assert mutate.cmd_update(
            prepared_run, "release_lineage", MERGE_COMMIT, db_path=db_path
        ) is None
        assert mutate.cmd_update(
            prepared_run, "release_lineage", MERGE_COMMIT, db_path=db_path
        ) is None
        conn = _conn(db_path)
        try:
            assert lineage_of(conn, prepared_run) == MERGE_COMMIT
        finally:
            conn.close()

    def test_a_different_commit_is_refused_and_both_are_named(
        self, db_path, prepared_run
    ):
        assert mutate.cmd_update(
            prepared_run, "release_lineage", MERGE_COMMIT, db_path=db_path
        ) is None
        refusal = mutate.cmd_update(
            prepared_run, "release_lineage", OTHER_COMMIT, db_path=db_path
        )
        assert refusal is not None
        assert MERGE_COMMIT in refusal
        assert OTHER_COMMIT in refusal
        assert "terminalize" in refusal

    def test_an_executing_run_will_not_have_its_lineage_rewritten(
        self, db_path, prepared_run
    ):
        assert mutate.cmd_update(
            prepared_run, "release_lineage", MERGE_COMMIT, db_path=db_path
        ) is None
        assert mutate.cmd_update(
            prepared_run, "status", "executing", db_path=db_path
        ) is None
        refusal = mutate.cmd_update(
            prepared_run, "release_lineage", OTHER_COMMIT, db_path=db_path
        )
        assert refusal is not None
        assert "executing" in refusal

    def test_a_partial_commit_is_refused(self, db_path, prepared_run):
        refusal = mutate.cmd_update(
            prepared_run, "release_lineage", "abc1234", db_path=db_path
        )
        assert refusal is not None
        assert "40-hex" in refusal


class TestTheStageAndProductionPair:
    """Two prepared runs for one item are ordinary when they differ by target.

    A release deploys stage and production in parallel from one verified
    revision, so refusing an item that advances two runs would strand half of
    every pair. Only two runs aimed at the SAME environment are ambiguous.
    """

    def _stage_environment(self, db_path: str) -> None:
        """A second deploy target for this project; the fixture seeds only prod."""
        conn = _conn(db_path)
        try:
            conn.execute(
                "INSERT INTO environments (id, site, project_id, name) "
                "VALUES (%s, 101, 1, 'stage') ON CONFLICT (id) DO NOTHING",
                (STAGE_ENVIRONMENT_ID,),
            )
            conn.commit()
        finally:
            conn.close()

    def _run_targeting(self, db_path: str, environment_id: int, item_id: int) -> str:
        """A prepared run aimed at one environment.

        Tier and environment are set together because the run row constrains
        them as a pair; setting only the environment is rejected.
        """
        run_id = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        mutate.cmd_add_item(run_id, item_id, db_path=db_path)
        conn = _conn(db_path)
        try:
            conn.execute(
                "UPDATE deployment_runs SET target_tier='persistent', "
                "target_environment_id=%s WHERE id=%s",
                (environment_id, run_id),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def test_runs_for_different_environments_are_both_legitimate(self, db_path):
        _insert_delivery_ready_item(db_path, PRODUCER_ITEM)
        self._stage_environment(db_path)
        stage = self._run_targeting(db_path, STAGE_ENVIRONMENT_ID, PRODUCER_ITEM)
        production = self._run_targeting(db_path, PROD_ENVIRONMENT_ID, PRODUCER_ITEM)
        conn = _conn(db_path)
        try:
            distinct, duplicates = split_runs_by_target_environment(
                conn, [stage, production]
            )
        finally:
            conn.close()
        assert sorted(distinct) == sorted([stage, production])
        assert duplicates == []

    def test_two_runs_for_one_environment_are_the_real_ambiguity(self, db_path):
        _insert_delivery_ready_item(db_path, PRODUCER_ITEM)
        first = self._run_targeting(db_path, PROD_ENVIRONMENT_ID, PRODUCER_ITEM)
        second = self._run_targeting(db_path, PROD_ENVIRONMENT_ID, PRODUCER_ITEM)
        conn = _conn(db_path)
        try:
            distinct, duplicates = split_runs_by_target_environment(
                conn, [first, second]
            )
        finally:
            conn.close()
        assert distinct == []
        assert [sorted(group) for group in duplicates] == [sorted([first, second])]

    def test_both_pair_runs_are_reachable_from_the_item(self, db_path):
        _insert_delivery_ready_item(db_path, PRODUCER_ITEM)
        self._stage_environment(db_path)
        stage = self._run_targeting(db_path, STAGE_ENVIRONMENT_ID, PRODUCER_ITEM)
        production = self._run_targeting(db_path, PROD_ENVIRONMENT_ID, PRODUCER_ITEM)
        conn = _conn(db_path)
        try:
            reachable = prepared_runs_awaiting_item(conn, PRODUCER_ITEM)
        finally:
            conn.close()
        assert sorted(reachable) == sorted([stage, production])
