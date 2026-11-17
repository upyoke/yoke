"""A takeover successor inherits operator removals, not automatic lineage releases.

An automatic release ("awaiting a later release") means the member's candidate
is outside the superseded run's frozen lineage. A successor whose pin contains
that candidate must be free to enroll it; an operator removal still follows the
item up the takeover chain.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from yoke_core.domain.deployment_member_candidate_release import (
    CORRECTION_RELEASE_REASON,
)
from yoke_core.domain.deployment_run_member_removal import (
    REOPENED_REASON,
    REPLACED_REASON,
)
from yoke_core.domain.deployment_run_membership_removals import (
    enrollment_removed_item_ids,
    record_membership_removals,
)

OLD, NEW = "run-20261117-002", "run-20261117-004"
RELEASED, REPLACED, REOPENED, OPERATOR = 5866, 5867, 5868, 5869


def _seed(conn) -> None:
    insert_deployment_run(conn, id=NEW, status="executing")
    insert_deployment_run(
        conn, id=OLD, status="succeeded", superseded_by_run_id=NEW
    )
    for item_id, reason in (
        (RELEASED, CORRECTION_RELEASE_REASON),
        (REPLACED, REPLACED_REASON),
        (REOPENED, REOPENED_REASON),
        (OPERATOR, "operator: not shipping this one"),
    ):
        record_membership_removals(
            conn, OLD, [item_id], reason=reason, session_id=None, actor_id=None
        )
    conn.commit()


def test_lineage_released_member_is_not_inherited_by_its_successor(test_db):
    _seed(test_db)

    inherited = enrollment_removed_item_ids(test_db, NEW)

    assert RELEASED not in inherited
    assert REPLACED not in inherited
    assert REOPENED not in inherited


def test_operator_removal_is_still_inherited(test_db):
    _seed(test_db)

    assert OPERATOR in enrollment_removed_item_ids(test_db, NEW)


def test_the_released_run_itself_still_excludes_the_member(test_db):
    _seed(test_db)

    assert RELEASED in enrollment_removed_item_ids(test_db, OLD)
