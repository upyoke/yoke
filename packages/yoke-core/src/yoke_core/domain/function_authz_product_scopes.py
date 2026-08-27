"""Explicit authorization scopes for workflow-aware product surfaces."""

from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    PERM_ORG_ADMIN,
    PERM_PROJECT_ADMIN,
    PERM_PROJECT_INSTALL,
)
from yoke_core.domain.function_authz_types import (
    ACTOR_SESSION,
    ORG,
    PROJECT,
    AuthzSpec,
)


PRODUCT_AUTHZ_BY_ID = {
    # Actor-visible lists and personal decision/preference surfaces.
    "items.overview.list": AuthzSpec(ACTOR_SESSION, None),
    "items.detail.get": AuthzSpec(ACTOR_SESSION, None),
    "inbox.list": AuthzSpec(ACTOR_SESSION, None),
    # A tenant member may create the pending request. Terminal decisions and
    # withdrawals still pass through the request's live org-admin authority.
    "machine_approval.lifecycle.apply": AuthzSpec(ACTOR_SESSION, None),
    "decision_requests.create": AuthzSpec(ACTOR_SESSION, None),
    "decision_requests.resolve": AuthzSpec(ACTOR_SESSION, None),
    "decision_requests.withdraw": AuthzSpec(ACTOR_SESSION, None),
    "notifications.read": AuthzSpec(ACTOR_SESSION, None),
    "notifications.read_all": AuthzSpec(ACTOR_SESSION, None),
    "overview.activation.get": AuthzSpec(ACTOR_SESSION, None),
    "overview.vitals.get": AuthzSpec(ACTOR_SESSION, None),
    "overview.module.dismiss": AuthzSpec(ACTOR_SESSION, None),
    "overview.module.restore": AuthzSpec(ACTOR_SESSION, None),
    "sessions.reclaim_stale": AuthzSpec(ORG, PERM_ORG_ADMIN),
    # Promotion materializes a Dash in the note's project (payload.project overrides).
    "ouroboros.field_note.promote": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    # Merge / done-transition engine-internal writes. Each mutates one
    # project's tenant data (path snapshot, item deployed_to/merged_at,
    # post-rebase QA), so the blast radius is PROJECT; they are
    # session-optional and claim-free because the done ceremony enforces the
    # item claim upstream at the status flip, not on these finalize writes.
    "project.snapshot.ensure_at": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "done_transition.finalize_local_side_effects": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "done_transition.populate_merged_at": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "merge_queue.landing_pending.mark": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "merge_queue.landing_pending.clear": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    # Pipeline member-item stamps (deploy_stage / deployed_to). Claim-free
    # because the deploy runner holds no session claim on member items; the
    # PROJECT + items-write scope is what gates the write. Do not route these
    # through items.scalar.update (claim gate) or a bare-digit items-update
    # CLI token (parsed as a public sequence, not items.id).
    "deployment_item_stamp.record": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    # The operator merge-timestamp repair writes one project's item row. It is
    # claim-free because a terminal item cannot be claimed at all -- that is the
    # gap it exists to close -- so this scope plus the human-only hook-context
    # refusal is what gates it.
    "items.merge_provenance.operator_correct": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    # The done-transition status flips (item -> done, epic-task -> done cascade)
    # bypass the item claim by design, so they are claim_required_kind=None; the
    # PROJECT + items-write scope is what gates the bypass to an authorized
    # caller (stronger than the old process-env trust).
    "done_transition.item_status_set": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "done_transition.epic_task_status_set": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    # Resync repair writes the new GitHub issue number back into one epic
    # task's github_issue field (one project's tenant data). It is
    # claim-free (the inline write it replaces opened a raw connection) and
    # session-optional (a resync run may resolve no ambient session), so the
    # PROJECT + items-write scope is what gates the write.
    "resync.epic_task_github_issue_set": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "merge.tests.post_rebase_requirement": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "merge.tests.record_post_rebase_ci_run": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    # Merge-lock rows are machine coordination, not tenant content: they hold
    # no item, carry no project target, and say only "a merge is in flight on
    # this branch". Any authenticated actor that can merge may take and
    # release one, so the scope is the actor's own session rather than a
    # project or org grant.
    "merge.lock.list": AuthzSpec(ACTOR_SESSION, None),
    "merge.lock.acquire": AuthzSpec(ACTOR_SESSION, None),
    "merge.lock.release": AuthzSpec(ACTOR_SESSION, None),
    # A project's GitHub binding state is that project's tenant data, so the
    # read is scoped to the project rather than the caller's own session. It
    # is claim-free: resolving auth is a precondition of merge, resync, and
    # label sync alike, none of which hold an item claim at that point. The
    # receipt write stamps the same project's binding row.
    "projects.github_state.read": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "projects.github_sync_receipt.record": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    # Workflow definition publication is org-wide; selected defaults and
    # test-machine execution remain scoped to their project.
    "workflows.current.set": AuthzSpec(ORG, PERM_ORG_ADMIN),
    # Taking a published update publishes a workflow version, so it
    # carries the same authority as selecting or editing one. Taking
    # several at once, and deciding whether the next one arrives without
    # being asked, are the same authority over the same definitions.
    "workflows.canon_update.apply": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflows.canon_update.apply_all": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflows.canon_follow.set": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflows.policy_defaults.publish": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflows.mechanics.get": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflows.testing_default.set": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "workflows.delivery_default.set": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "workflows.approval_defaults.publish": AuthzSpec(ORG, PERM_ORG_ADMIN),
    # Execution instructions are org-wide operator prose layered onto every
    # matching item fetch, so authoring them carries workflow-definition
    # authority; authenticated agents may read either the editor list or only
    # the instructions resolved for the workflow/project they are filing.
    "workflow.execution_instruction.create": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflow.execution_instruction.update": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflow.execution_instruction.set_scope": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflow.execution_instruction.delete": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflow.execution_instruction.resolve": AuthzSpec(ACTOR_SESSION, None),
    "workflow.execution_instruction.list": AuthzSpec(ACTOR_SESSION, None),
    "qa.case.waive": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.case_execution.begin": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.begin": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.heartbeat": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.advance": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.complete": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.abort": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_review.begin": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_review.submit": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "test_machine.get": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "test_machine.settings_replace": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "test_machine.verify": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "test_machine.verify.abort": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "test_machine.verify.begin": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "test_machine.verify.submit": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "test_machine.baseline_group.abort": AuthzSpec(
        PROJECT,
        PERM_ITEMS_WRITE,
    ),
    "test_machine.baseline_group_execute": AuthzSpec(
        PROJECT,
        PERM_ITEMS_WRITE,
    ),
    "test_machine.baseline_group.begin": AuthzSpec(
        PROJECT,
        PERM_ITEMS_WRITE,
    ),
    "test_machine.baseline_group.submit": AuthzSpec(
        PROJECT,
        PERM_ITEMS_WRITE,
    ),
    "test_machine.case.abort": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "test_machine.case_execute": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "test_machine.case.begin": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "test_machine.case.submit": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "test_machine.plan_case.begin": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "test_machine.plan_case.submit": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "test_machine.mission.ready": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "test_machine.mission.access": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
}


__all__ = ["PRODUCT_AUTHZ_BY_ID"]
