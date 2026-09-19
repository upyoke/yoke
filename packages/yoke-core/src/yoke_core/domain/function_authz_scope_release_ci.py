"""What a scoped release or CI identity may do, carved out by function id.

A hosted release runs as a project-scoped machine identity — the release
bridge, the deploy driver — and those identities must never hold project or
org administration. Every function here is therefore lifted out of a broader
default (``github_actions.*`` project-admin, ``deployment_runs.*`` org-admin)
and re-authorized on one narrow permission naming exactly the act it allows.

Keeping them together is the point: this file is the whole answer to "what
can a release token do", which is the question asked whenever one of these
grants is widened. Adding an entry here widens that answer, so add one only
with the narrow permission the act needs, and grant that permission to the
release role alone.
"""

from yoke_core.domain.actor_permissions import (
    PERM_GITHUB_ACTIONS_RUN_READ,
    PERM_GITHUB_ACTIONS_VARIABLE_READ,
    PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
    PERM_GITHUB_RELEASE_CREATE,
    PERM_RELEASE_OUTPUT_RECORD,
    PERM_RELEASE_PIN_RECORD,
)
from yoke_core.domain.function_authz_types import PROJECT, AuthzSpec


RELEASE_CI_AUTHZ_BY_ID = {
    "release_pin.record": AuthzSpec(PROJECT, PERM_RELEASE_PIN_RECORD),
    # The bridge attributes the version-pin commit its own promotion pushed.
    # Carved out of the deployment_runs.* org-admin prefix for the same
    # reason release_pin.record is carved out of project admin: the only
    # caller is a release identity, and the act is one narrow write.
    "deployment_runs.release_output.record": AuthzSpec(
        PROJECT,
        PERM_RELEASE_OUTPUT_RECORD,
    ),
    "github.release.create_next_tag": AuthzSpec(
        PROJECT,
        PERM_GITHUB_RELEASE_CREATE,
    ),
    # Hosted deploy runners may trigger and observe the project's deployment
    # workflows without receiving project administration. Every other
    # github_actions.* function keeps the project-admin prefix default below.
    "github_actions.workflow.dispatch": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
    ),
    "github_actions.workflow.dispatch_once": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
    ),
    "github_actions.workflow.find_run": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_RUN_READ,
    ),
    "github_actions.run.jobs_count": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_RUN_READ,
    ),
    "github_actions.wait_run": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_RUN_READ,
    ),
    "github_actions.check_ci": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_RUN_READ,
    ),
    "github_actions.failed_log": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_RUN_READ,
    ),
    "deployment_runs.failure_trace": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_RUN_READ,
    ),
    "github_actions.variable.get": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_VARIABLE_READ,
    ),
}


__all__ = ["RELEASE_CI_AUTHZ_BY_ID"]
