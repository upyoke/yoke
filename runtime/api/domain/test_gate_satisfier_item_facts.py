"""Delivery facts resolve inherited defaults before stamping merge-only proof."""

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.gate_satisfier_facts import CapabilityFacts, FactVerdict
from yoke_core.domain.gate_satisfier_item_facts import (
    ITEM_NO_DEPLOYMENT_TARGET,
    load_item_facts,
)
from yoke_core.domain.gate_satisfier_ladder import resolve_ladder
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    DELIVERY_EVIDENCE_LADDER,
    OBSERVED_MERGE_RECORDED,
)
from yoke_core.domain.workflow_project_defaults import set_delivery_default


def test_null_flow_with_deploying_default_cannot_satisfy_merge_only(test_db):
    item_id = 29401
    flow_id = "production-delivery"
    cmd_create(
        test_db,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps([{"name": "deploy", "step_runner": "auto"}]),
        target_tier="persistent",
        environment="development",
    )
    set_delivery_default(
        test_db,
        project="yoke",
        workflow_id="dash",
        flow_id=flow_id,
    )
    insert_item(test_db, id=item_id, workflow_id="dash", deployment_flow=None)

    facts = CapabilityFacts(facts=load_item_facts(test_db, item_id)).with_observed(
        {
            OBSERVED_MERGE_RECORDED: (True, "the item merged"),
        }
    )
    fact = facts.facts[ITEM_NO_DEPLOYMENT_TARGET]
    resolution = resolve_ladder(DELIVERY_EVIDENCE_LADDER, facts)

    assert fact.verdict == FactVerdict.ABSENT
    assert fact.value == flow_id
    assert resolution.satisfied is False
    assert (
        test_db.execute(
            "SELECT deployment_flow FROM items WHERE id=%s",
            (item_id,),
        ).fetchone()[0]
        is None
    )
