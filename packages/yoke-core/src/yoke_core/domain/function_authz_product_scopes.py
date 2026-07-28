"""Explicit authorization scopes for workflow-aware product surfaces."""

from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    PERM_ORG_ADMIN,
    PERM_PROJECT_ADMIN,
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
    # Promotion materializes a Dash in payload.project.
    "ouroboros.field_note.promote": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    # Workflow definition publication is org-wide; selected defaults and
    # test-machine execution remain scoped to their project.
    "workflows.current.set": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflows.policy_defaults.publish": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflows.mechanics.get": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "workflows.testing_default.set": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "workflows.delivery_default.set": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "workflows.approval_defaults.publish": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "qa.case.rerun": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.case.waive": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.case_execution.begin": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.begin": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.heartbeat": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.advance": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.complete": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "qa.plan_execution.abort": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
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
}


__all__ = ["PRODUCT_AUTHZ_BY_ID"]
