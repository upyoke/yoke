"""A claimed item standing at its pinned release wait is a declared wait.

Its remaining work belongs to a deployment run, exactly as an armed,
unlanded landing belongs to the merge queue, so the same claim fact
answers yes and idle-holder alarms leave its parked holder alone.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.sessions_holdings_claim_facts import (
    ITEM_AWAITING_LANDING_KEY,
    claimed_item_facts,
)


@pytest.mark.parametrize("status,waiting", [("release", True), ("implementing", False)])
def test_release_stage_reads_as_a_declared_wait(test_db, status, waiting):
    insert_item(test_db, id=9401, workflow_id="issue", status=status)
    test_db.commit()

    facts = claimed_item_facts(test_db, [9401])[9401]

    assert facts[ITEM_AWAITING_LANDING_KEY] is waiting
