"""A stage run that delivered does not hold a member that owes prod.

Custody is judged against the item's completion target. A member whose only
holder is a succeeded stage run reads "delivered to stage; awaiting prod",
not "awaiting <stage flow> release", which named a release already done.
"""

from __future__ import annotations

import json
from uuid import uuid4

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.delivery_landing_custody import HELD
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.steering_fleet_report_landed_gate import (
    AWAITING_RELEASE,
    LandedGate,
)
from yoke_core.domain.steering_fleet_report_landed_open import (
    LandedItem,
    landed_without_closeout,
)
from yoke_core.domain.steering_fleet_report_landed_phrases import (
    release_wait_phrase,
)

NOW = "2026-11-18T18:00:00.000000Z"
PROD_FLOW = "hosted-production"


def _landing(**changes) -> LandedItem:
    fields = dict(
        item_id=5373,
        public_ref="TEST-5373",
        status="release",
        at_release=True,
        landed_at=NOW,
        landed_seconds=3600,
        workflow_id="dash",
        completion_flow_available=True,
        delivery_gate=LandedGate(AWAITING_RELEASE, flow=PROD_FLOW),
        custody_state=HELD,
        custody_run_id=str(uuid4()),
        custody_run_flow="hosted-stage-release-qa",
        delivered_to="stage",
        owed_elsewhere=(("post_deploy QA", "prod"),),
        completion_target="prod",
    )
    fields.update(changes)
    return LandedItem(**fields)


def test_stage_delivered_member_that_owes_prod_awaits_prod():
    assert release_wait_phrase(_landing()) == (
        "delivered to stage; awaiting prod (claim released after landing; the release carries it)"
    )


def test_holder_on_the_completion_target_still_names_its_release():
    phrase = release_wait_phrase(
        _landing(delivered_to="", owed_elsewhere=(), custody_run_flow=PROD_FLOW)
    )
    assert phrase.startswith(f"awaiting {PROD_FLOW} release — delivering in ")


def test_landed_rows_carry_the_completion_flow_environment(test_db):
    """The fixture project registers ``development``; it stands in for prod."""
    insert_item(
        test_db,
        id=1,
        title="Awaiting prod",
        workflow_id="dash",
        status="release",
        merged_at=NOW,
    )
    stages = [{"name": "deploy", "stage_kind": "execution", "step_runner": "auto"}]
    cmd_create(
        test_db,
        PROD_FLOW,
        "yoke",
        PROD_FLOW,
        "",
        json.dumps(stages),
        target_tier="persistent",
        environment="development",
    )
    test_db.execute("UPDATE items SET deployment_flow=%s WHERE id=1", (PROD_FLOW,))

    (entry,) = landed_without_closeout(test_db, project_id=1, now=NOW, holders=())

    assert entry.completion_target == "development"
