"""Each registered obligation's rungs resolve as the gates expect.

The catalog is data every migrated gate reads, so these lock in the
ordering and the reachability conditions rather than the prose.
"""

from __future__ import annotations

from yoke_core.domain.gate_satisfier_facts import (
    CapabilityFacts,
    Fact,
    FactVerdict,
    OBSERVED_LOCAL_INTEGRATION_REF,
    OBSERVED_MERGE_RECORDED,
    OBSERVED_NO_IMPLEMENTATION_BRANCH,
    OBSERVED_REMOTE_INTEGRATION_REF,
    DERIVED_ENVIRONMENTS_PRESENT,
    capability_fact,
)
from yoke_core.domain.gate_satisfier_item_facts import (
    ITEM_CI_VERDICT,
    ITEM_DEPLOYMENT_RUN_SUCCEEDED,
    ITEM_NO_DEPLOYMENT_TARGET,
)
from yoke_core.domain.gate_satisfier_ladder import resolve_ladder
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    DELIVERY_EVIDENCE_LADDER,
    DONE_MERGE_EVIDENCE_LADDER,
    LADDERS,
    PATH_CLAIM_BOUNDARY_LADDER,
)


def _present(*keys: str) -> CapabilityFacts:
    return CapabilityFacts(
        facts={
            key: Fact(key=key, verdict=FactVerdict.PRESENT, detail="fixture")
            for key in keys
        }
    )


def test_every_catalog_entry_is_keyed_by_its_own_obligation():
    for obligation, ladder in LADDERS.items():
        assert ladder.obligation == obligation


def test_boundary_prefers_the_remote_ref_over_the_local_one():
    facts = _present(
        OBSERVED_REMOTE_INTEGRATION_REF, OBSERVED_LOCAL_INTEGRATION_REF
    )
    assert (
        resolve_ladder(PATH_CLAIM_BOUNDARY_LADDER, facts).rung_id
        == "remote_integration_ref"
    )


def test_boundary_uses_the_local_ref_when_there_is_no_remote():
    facts = _present(OBSERVED_LOCAL_INTEGRATION_REF)
    assert (
        resolve_ladder(PATH_CLAIM_BOUNDARY_LADDER, facts).rung_id
        == "local_integration_ref"
    )


def test_boundary_refuses_when_no_ref_resolves():
    assert not resolve_ladder(
        PATH_CLAIM_BOUNDARY_LADDER, CapabilityFacts(facts={})
    ).satisfied


def test_merge_evidence_takes_the_ci_rung_when_ci_is_declared_and_green():
    facts = _present(
        capability_fact("ci_workflow_file"),
        OBSERVED_MERGE_RECORDED,
        ITEM_CI_VERDICT,
    )
    assert (
        resolve_ladder(DONE_MERGE_EVIDENCE_LADDER, facts).rung_id
        == "merged_with_ci"
    )


def test_merge_evidence_falls_to_merged_locally_without_ci():
    facts = _present(OBSERVED_MERGE_RECORDED)
    assert (
        resolve_ladder(DONE_MERGE_EVIDENCE_LADDER, facts).rung_id
        == "merged_locally"
    )


def test_declared_ci_with_no_verdict_still_reaches_the_local_merge_rung():
    facts = _present(
        capability_fact("ci_workflow_file"), OBSERVED_MERGE_RECORDED
    )
    resolution = resolve_ladder(DONE_MERGE_EVIDENCE_LADDER, facts)
    assert resolution.rung_id == "merged_locally"
    assert resolution.rejected[0].missing_fact == ITEM_CI_VERDICT


def test_merge_evidence_attests_when_no_implementation_branch_exists():
    facts = _present(OBSERVED_NO_IMPLEMENTATION_BRANCH)
    assert (
        resolve_ladder(DONE_MERGE_EVIDENCE_LADDER, facts).rung_id
        == "agent_attested"
    )


def test_an_unmerged_existing_branch_reaches_no_merge_rung():
    facts = CapabilityFacts(
        facts={
            OBSERVED_MERGE_RECORDED: Fact(
                key=OBSERVED_MERGE_RECORDED,
                verdict=FactVerdict.ABSENT,
                detail="not merged",
            ),
            OBSERVED_NO_IMPLEMENTATION_BRANCH: Fact(
                key=OBSERVED_NO_IMPLEMENTATION_BRANCH,
                verdict=FactVerdict.ABSENT,
                detail="a branch exists",
            ),
        }
    )
    resolution = resolve_ladder(DONE_MERGE_EVIDENCE_LADDER, facts)
    assert resolution.satisfied is False


def test_delivery_prefers_a_succeeded_deployment_run():
    facts = _present(
        DERIVED_ENVIRONMENTS_PRESENT,
        ITEM_DEPLOYMENT_RUN_SUCCEEDED,
        ITEM_NO_DEPLOYMENT_TARGET,
        OBSERVED_MERGE_RECORDED,
    )
    assert (
        resolve_ladder(DELIVERY_EVIDENCE_LADDER, facts).rung_id
        == "deployment_run_succeeded"
    )


def test_delivery_stamps_merge_only_for_a_project_with_no_target():
    facts = _present(ITEM_NO_DEPLOYMENT_TARGET, OBSERVED_MERGE_RECORDED)
    assert (
        resolve_ladder(DELIVERY_EVIDENCE_LADDER, facts).rung_id == "merge_only"
    )


def test_a_real_deployment_target_puts_merge_only_out_of_reach():
    facts = CapabilityFacts(
        facts={
            OBSERVED_MERGE_RECORDED: Fact(
                key=OBSERVED_MERGE_RECORDED,
                verdict=FactVerdict.PRESENT,
                detail="merged",
            ),
            ITEM_NO_DEPLOYMENT_TARGET: Fact(
                key=ITEM_NO_DEPLOYMENT_TARGET,
                verdict=FactVerdict.ABSENT,
                detail="the flow targets a tier",
            ),
        }
    )
    resolution = resolve_ladder(DELIVERY_EVIDENCE_LADDER, facts)
    assert resolution.satisfied is False
    assert "usher" in DELIVERY_EVIDENCE_LADDER.remedy
