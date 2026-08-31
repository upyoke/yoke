"""The satisfier ladders every migrated gate resolves.

Each entry is one obligation plus the ordered rungs that can discharge
it, highest first. The ladders are data: one immutable workflow
definition serves a bare folder, a laptop-only git repository, and a
full hosted stack, because what differs between those shapes is which
rung resolves — not which gates exist.

Read each ladder top-down as "the strongest proof this project can
offer, then the next strongest". Read the ``remedy`` as what an operator
does when the project can offer none.
"""

from __future__ import annotations

from yoke_core.domain.gate_satisfier_facts import (
    DECLARED_DEFAULT_BRANCH,
    DERIVED_DEFAULT_BRANCH,
    DERIVED_ENVIRONMENTS_PRESENT,
    OBSERVED_LOCAL_INTEGRATION_REF,
    OBSERVED_MERGE_RECORDED,
    OBSERVED_NO_IMPLEMENTATION_BRANCH,
    OBSERVED_REMOTE_INTEGRATION_REF,
    capability_fact,
)
from yoke_core.domain.gate_satisfier_item_facts import (
    ITEM_CI_VERDICT,
    ITEM_DEPLOYMENT_RUN_SUCCEEDED,
    ITEM_NO_DEPLOYMENT_TARGET,
)
from yoke_core.domain.gate_satisfier_ladder import SatisfierLadder, SatisfierRung


OBLIGATION_PATH_CLAIM_BOUNDARY = "path_claim_boundary"
OBLIGATION_DONE_MERGE_EVIDENCE = "done_merge_evidence"
OBLIGATION_DELIVERY_EVIDENCE = "delivery_evidence"
OBLIGATION_INTEGRATION_TRUNK = "integration_trunk"


PATH_CLAIM_BOUNDARY_LADDER = SatisfierLadder(
    obligation=OBLIGATION_PATH_CLAIM_BOUNDARY,
    statement=(
        "Every path this item committed must fall inside the coverage it "
        "declared, diffed against the integration target."
    ),
    rungs=(
        SatisfierRung(
            rung_id="remote_integration_ref",
            summary=(
                "diff against refs/remotes/origin/<target> — what the "
                "shared remote will actually integrate"
            ),
            requires=(OBSERVED_REMOTE_INTEGRATION_REF,),
        ),
        SatisfierRung(
            rung_id="local_integration_ref",
            summary=(
                "diff against refs/heads/<target> — the local trunk a "
                "git-only project integrates into"
            ),
            requires=(OBSERVED_LOCAL_INTEGRATION_REF,),
        ),
    ),
    remedy=(
        "the item holds path claims but neither a remote nor a local "
        "integration ref resolves in its worktree. Fetch the remote, "
        "create the local trunk branch, or repair the item's recorded "
        "worktree with `yoke item-worktrees path-record`. This gate does "
        "not pass on an unresolvable target: an unchecked boundary and a "
        "clean boundary are not the same answer."
    ),
)


DONE_MERGE_EVIDENCE_LADDER = SatisfierLadder(
    obligation=OBLIGATION_DONE_MERGE_EVIDENCE,
    statement=(
        "An item reaching done must record how its work became part of "
        "the trunk."
    ),
    rungs=(
        SatisfierRung(
            rung_id="merged_with_ci",
            summary=(
                "the lane merged and the project's CI workflow returned a "
                "verdict on the merged commit"
            ),
            requires=(
                capability_fact("ci_workflow_file"),
                OBSERVED_MERGE_RECORDED,
                ITEM_CI_VERDICT,
            ),
            declared_by_capability="ci_workflow_file",
        ),
        SatisfierRung(
            rung_id="merged_locally",
            summary="the lane branch merged into the trunk in this checkout",
            requires=(OBSERVED_MERGE_RECORDED,),
        ),
        SatisfierRung(
            rung_id="agent_attested",
            summary=(
                "no implementation branch ever existed, so the recorded "
                "evidence — not a merge — is the whole proof"
            ),
            requires=(OBSERVED_NO_IMPLEMENTATION_BRANCH,),
        ),
    ),
    remedy=(
        "an implementation branch exists for this item and was not "
        "merged. Merge the lane (`yoke merge item <ITEM>`), or delete "
        "the branch if the work genuinely produced no commits. Reaching "
        "done past an unmerged branch would record work as delivered "
        "that no trunk contains."
    ),
)


DELIVERY_EVIDENCE_LADDER = SatisfierLadder(
    obligation=OBLIGATION_DELIVERY_EVIDENCE,
    statement=(
        "A workflow whose delivery policy names a release must record "
        "what delivery actually happened."
    ),
    rungs=(
        SatisfierRung(
            rung_id="deployment_run_succeeded",
            summary=(
                "an item-bound deployment run reached succeeded against a "
                "registered environment"
            ),
            requires=(
                DERIVED_ENVIRONMENTS_PRESENT,
                ITEM_DEPLOYMENT_RUN_SUCCEEDED,
            ),
        ),
        SatisfierRung(
            rung_id="merge_only",
            summary=(
                "the project registers no deployment target, so landing on "
                "the trunk IS the delivery"
            ),
            requires=(ITEM_NO_DEPLOYMENT_TARGET, OBSERVED_MERGE_RECORDED),
        ),
    ),
    remedy=(
        "this item declares a deployment flow with a real target tier but "
        "has no successful run, and it did not merge either. Run "
        "`/yoke usher <ITEM>` to deploy, or clear "
        "`items.deployment_flow` if this item genuinely delivers by "
        "merging. An empty flow no longer means 'skip the obligation' — "
        "it selects the merge-only rung and records it."
    ),
)


INTEGRATION_TRUNK_LADDER = SatisfierLadder(
    obligation=OBLIGATION_INTEGRATION_TRUNK,
    statement=(
        "Every branch operation needs to know which branch this project "
        "integrates into."
    ),
    rungs=(
        SatisfierRung(
            rung_id="declared_default_branch",
            summary="projects.default_branch, authored by the operator",
            requires=(DECLARED_DEFAULT_BRANCH,),
        ),
        SatisfierRung(
            rung_id="derived_default_branch",
            summary=(
                "the default branch the project's recorded remote reports, "
                "converged at project snapshot sync"
            ),
            requires=(DERIVED_DEFAULT_BRANCH,),
        ),
    ),
    remedy=(
        "this project names no trunk. Set one with "
        "`yoke projects update --slug <SLUG> --name <NAME> "
        "--default-branch <BRANCH>`. "
        "Assuming 'main' is how work lands on the wrong base and only "
        "fails much later, so the trunk is required rather than guessed."
    ),
)


LADDERS = {
    ladder.obligation: ladder
    for ladder in (
        PATH_CLAIM_BOUNDARY_LADDER,
        DONE_MERGE_EVIDENCE_LADDER,
        DELIVERY_EVIDENCE_LADDER,
        INTEGRATION_TRUNK_LADDER,
    )
}


__all__ = [
    "DELIVERY_EVIDENCE_LADDER",
    "DONE_MERGE_EVIDENCE_LADDER",
    "INTEGRATION_TRUNK_LADDER",
    "LADDERS",
    "OBLIGATION_DELIVERY_EVIDENCE",
    "OBLIGATION_DONE_MERGE_EVIDENCE",
    "OBLIGATION_INTEGRATION_TRUNK",
    "OBLIGATION_PATH_CLAIM_BOUNDARY",
    "PATH_CLAIM_BOUNDARY_LADDER",
]
