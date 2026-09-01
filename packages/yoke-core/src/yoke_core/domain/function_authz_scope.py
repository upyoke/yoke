"""Per-function authorization-scope classification for Yoke function dispatch.

Every registered function is sorted by *blast radius*; the dispatch
(``check_dispatch_permission``) routes its permission check to this scope:

* ``PROJECT``        — checked against the op's real target project (the project
                       its data belongs to). Tenant content: items, claims,
                       events, qa, a specific project's settings/secrets.
* ``ORG``            — checked against the op's target org (org admin). Org-entity
                       and cross-project registry ops: create a project,
                       deployment flows/runs.
* ``CONTROL_PLANE``  — checked against the universe's sole organization and
                       requires the function's explicit org-scoped permission.
                       Whole-DB / whole-instance diagnostics: raw db read,
                       doctor. Project slugs never confer control-plane authority.
* ``ACTOR_SESSION``  — own-session and global learning-channel operations;
                       allowed for any authenticated actor without a tenant target.
* ``CLIENT_LOCAL``   — machine-local work gated by machine possession.
* ``DENY``           — fail-closed: an unclassified *side-effecting* function.

This table is the security spec. The safe default for anything not classified here
is DENY for writes / allow-but-audit for pure reads (see ``classify``).
"""

from __future__ import annotations

from yoke_core.domain.actor_permissions import (
    PERM_BOARD_REBUILD,
    PERM_CLAIMS_ACQUIRE,
    PERM_CLAIMS_RELEASE,
    PERM_DB_READ_RAW,
    PERM_EVENTS_READ,
    PERM_EVENTS_WRITE,
    PERM_GITHUB_ACTIONS_RUN_READ,
    PERM_GITHUB_ACTIONS_VARIABLE_READ,
    PERM_GITHUB_ACTIONS_WORKFLOW_DISPATCH,
    PERM_GITHUB_RELEASE_CREATE,
    PERM_HOOKS_EVALUATE,
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    PERM_ORG_ADMIN,
    PERM_PROJECT_ADMIN,
    PERM_PROJECT_CREATE,
    PERM_PROJECT_INSTALL,
    PERM_PROJECT_RENDER_READ,
    PERM_RELEASE_PIN_RECORD,
)
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.function_authz_product_scopes import PRODUCT_AUTHZ_BY_ID
from yoke_core.domain.function_authz_scope_client_local import (
    CLIENT_LOCAL_BY_ID,
)
from yoke_core.domain.function_authz_scope_control_plane import (
    CONTROL_PLANE_AUTHZ_BY_ID,
)
from yoke_core.domain.function_authz_scope_prefixes import AUTHZ_BY_PREFIX
from yoke_core.domain.function_authz_types import (
    ACTOR_SESSION,
    CLIENT_LOCAL,
    CONTROL_PLANE,
    DENY,
    ORG,
    PROJECT,
    AuthzSpec,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry

# function_id -> (scope, permission). PROJECT families are handled by
# permission_key_for and need no entry here.
_BY_ID: dict[str, AuthzSpec] = {
    **PRODUCT_AUTHZ_BY_ID,
    **CONTROL_PLANE_AUTHZ_BY_ID,
    # Actor-visible item inventory. The handlers filter rows to the actor's
    # org/project grants; local source-dev calls without a numeric actor remain
    # unfiltered.
    "items.list.run": AuthzSpec(ACTOR_SESSION, None),
    "items.search.run": AuthzSpec(ACTOR_SESSION, None),
    # Actor-visible project inventory. The handler filters rows to the actor's
    # org/project grants; local source-dev calls without a numeric actor remain
    # unfiltered.
    "projects.list": AuthzSpec(ACTOR_SESSION, None),
    # The org identity card (slug/name/created_at) is instance identity, not
    # tenant content — readable by any authenticated actor.
    "organizations.get": AuthzSpec(ACTOR_SESSION, None),
    "organizations.settings.catalog": AuthzSpec(ACTOR_SESSION, None),
    "organizations.settings.get": AuthzSpec(ACTOR_SESSION, None),
    "organizations.settings.merge": AuthzSpec(ORG, PERM_ORG_ADMIN),
    "organizations.domain.set": AuthzSpec(ORG, PERM_ORG_ADMIN),
    # Note: ouroboros.entry.* writes are deliberately absent here. Review and
    # archive mutate one project's queue, so they take the PROJECT scope
    # permission_key_for assigns; a session scope would expose every project.
    # Any authenticated session may refresh this deterministic server-owned
    # relationship map after rendering local agent adapters. No caller-authored
    # path or value crosses the boundary.
    "agents.render_relationships.record": AuthzSpec(ACTOR_SESSION, None),
    # Registering a NEW project in the org is an org-admin act.
    "projects.create": AuthzSpec(ORG, PERM_PROJECT_CREATE),
    # Editing an EXISTING project is scoped to that project's admin (the target
    # project resolves from the payload slug/id).
    "projects.update": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    # Per-project settings / secrets / metadata — checked against the TARGET
    # project (resolved from the payload), gated by that project's admin.
    "projects.capability_secret.set": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "projects.capability_settings.get": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "projects.capability_settings.set": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "projects.capability_settings.merge": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "projects.capability_settings.remove": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "projects.environment_settings.get": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "projects.infrastructure.list": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "projects.environment_settings.merge": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "release_pin.record": AuthzSpec(PROJECT, PERM_RELEASE_PIN_RECORD),
    "projects.pulumi_state.migrate": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "projects.pulumi_state.checkpoint_import": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    # Site/environment registration: the install grant, like onboard.checklist.*.
    "projects.site.create": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "projects.environment.create": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "projects.environment.update": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "projects.pulumi_stack_config.get": AuthzSpec(
        PROJECT,
        PERM_PROJECT_RENDER_READ,
    ),
    "projects.capability.has": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    # Project identity metadata is visible to every actor who belongs to the
    # project.  The handler applies the same actor-visible filter as
    # projects.list, so specialized service roles do not need backlog access.
    "projects.get": AuthzSpec(ACTOR_SESSION, None),
    "projects.resolve_by_github_repo": AuthzSpec(ACTOR_SESSION, None),
    "projects.checkout_context.run": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "projects.github_binding.bind": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    # Hosted lifecycle deliveries mutate one verified project binding. The
    # HTTP boundary separately requires the hosted service token; dispatch
    # authority follows payload.project so tenant universes never depend on a
    # project literally named ``yoke``.
    "projects.github_binding.lifecycle": AuthzSpec(
        PROJECT,
        PERM_PROJECT_ADMIN,
    ),
    "projects.github_binding.unbind": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    # Repository binding status contains project identity and non-secret App
    # metadata needed by both human viewers and infrastructure renderers.  The
    # handler constrains numeric actors to their visible projects, matching
    # projects.get without granting a CI role access to backlog items.
    "projects.github_binding.status": AuthzSpec(ACTOR_SESSION, None),
    "project.snapshot.sync": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "deployment_flows.create": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "packs.list": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "packs.bundle.get": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "packs.project.report": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "path_claims.conflicts.list": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "github.pr.create": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "github.merge_queue.apply": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
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
    "conduct.epic_task.update_status": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "conduct.epic.proceed_triage_handoff": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "onboard.checklist.init": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "onboard.checklist.run": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    # Actor/session: caller operating on its own session/orchestration.
    "sessions.begin": AuthzSpec(ACTOR_SESSION, None),
    "sessions.touch": AuthzSpec(ACTOR_SESSION, None),
    "sessions.offer": AuthzSpec(ACTOR_SESSION, None),
    "sessions.checkpoint": AuthzSpec(ACTOR_SESSION, None),
    "sessions.checkpoint_read": AuthzSpec(ACTOR_SESSION, None),
    "sessions.end_if_empty": AuthzSpec(ACTOR_SESSION, None),
    "sessions.ownership_guard": AuthzSpec(ACTOR_SESSION, None),
    # The handler releases only rows owned by request.actor.session_id.  It may
    # span projects, so forcing a single PROJECT scope is both unnecessary and
    # impossible for a session that legitimately holds more than one claim.
    "claims.work.release_session_scoped": AuthzSpec(ACTOR_SESSION, None),
    "charge.schedule": AuthzSpec(ACTOR_SESSION, None),
    # Reads every steering claim this session holds. A PROJECT target cannot
    # name that set; --project is an optional filter the handler applies.
    "steering.report.get": AuthzSpec(ACTOR_SESSION, None),
    **CLIENT_LOCAL_BY_ID,
}


def classify(
    function_id: str,
    *,
    side_effects: bool,
    project_permission: str | None,
) -> AuthzSpec:
    """Return the :class:`AuthzSpec` for a registered function.

    ``project_permission`` is ``permission_key_for(entry)`` — passed in by the
    caller so this module never imports the dispatch layer (one-directional).

    Precedence: explicit by-id → explicit by-prefix → PROJECT (when
    permission_key_for assigned a project permission) → fail-closed default
    (DENY for side-effecting, allow-but-classify for pure reads).
    """
    spec = _BY_ID.get(function_id)
    if spec is not None:
        return spec
    for prefix, prefix_spec in AUTHZ_BY_PREFIX:
        if function_id.startswith(prefix):
            return prefix_spec
    if project_permission is not None:
        return AuthzSpec(PROJECT, project_permission)
    # Unclassified. A side-effecting function fails closed; a pure read is
    # allowed (no shared-state mutation) but should be classified explicitly —
    # the dispatch emits a telemetry signal so these surface for follow-up.
    if side_effects:
        return AuthzSpec(DENY, None)
    return AuthzSpec(CLIENT_LOCAL, None)


def is_explicit_client_local(function_id: str) -> bool:
    """True iff ``function_id`` is EXPLICITLY classified ``CLIENT_LOCAL``.

    Checks only the by-id / by-prefix tables — no registry entry,
    ``side_effects``, or ``project_permission`` needed. These are the
    machine-local / aggregate ops (``status``, ``env use``, render,
    ``packs.get.run``, ``project.install`` family, …) that resolve to a
    registered subcommand but route NO single function-call dispatch.
    The recipe smoke uses this to verify such commands *resolve* without
    expecting a captured dispatch (and without argparse-running a bare
    reference-listing command name). The fall-through ``CLIENT_LOCAL``
    in :func:`classify` (an unclassified pure read) is deliberately not
    treated as client-local here — such reads do route a dispatch.
    """
    spec = _BY_ID.get(function_id)
    if spec is not None:
        return spec.scope == CLIENT_LOCAL
    for prefix, prefix_spec in AUTHZ_BY_PREFIX:
        if function_id.startswith(prefix):
            return prefix_spec.scope == CLIENT_LOCAL
    return False


def permission_key_for(entry: RegistryEntry) -> str | None:
    """Return the stable project-scoped permission key for a registered function.

    The legacy per-family mapping (project-scoped permissions only); it feeds
    ``classify`` as the PROJECT-bucket permission. Org/control-plane/session/
    local scopes are assigned by the explicit tables above, not here.
    """
    fid = entry.function_id
    if fid == "hook.evaluate.run":
        return PERM_HOOKS_EVALUATE
    if fid == "board.rebuild.run":
        return PERM_BOARD_REBUILD
    if fid == "board.data.get":
        return PERM_ITEMS_READ
    if fid == "project_structure.patch.apply":
        return PERM_PROJECT_ADMIN
    if fid == DB_READ_FUNCTION_ID:
        return PERM_DB_READ_RAW
    if fid.startswith(("items.", "workflow_item.", "item_worktrees.")):
        return PERM_ITEMS_WRITE if entry.side_effects else PERM_ITEMS_READ
    if fid.startswith("direct_workflow."):
        return PERM_ITEMS_WRITE
    if fid.startswith(("workflows.item.", "workflows.item_posture.")):
        return PERM_ITEMS_WRITE if entry.side_effects else PERM_ITEMS_READ
    if fid.startswith("lifecycle."):
        return PERM_ITEMS_WRITE
    if fid.startswith("claims."):
        if ".release" in fid:
            return PERM_CLAIMS_RELEASE
        if entry.side_effects:
            return PERM_CLAIMS_ACQUIRE
        return PERM_ITEMS_READ
    if fid == "db_claim.amend":
        return PERM_ITEMS_WRITE
    if fid.startswith("gate_satisfier."):
        # Resolving an obligation's satisfier ladder stamps the rung on
        # the item, so it is an item write even though the caller is the
        # engine rather than an authoring agent.
        return PERM_ITEMS_WRITE
    if fid.startswith("strategy."):
        return PERM_ITEMS_WRITE if entry.side_effects else PERM_ITEMS_READ
    if fid.startswith("events."):
        return PERM_EVENTS_WRITE if entry.side_effects else PERM_EVENTS_READ
    if fid == "ephemeral_env.get":
        return PERM_ITEMS_READ
    if fid.startswith("ephemeral_env."):
        return PERM_ITEMS_WRITE
    if fid.startswith("ouroboros.entry."):
        return PERM_EVENTS_WRITE if entry.side_effects else PERM_EVENTS_READ
    if fid.startswith("shepherd."):
        return PERM_ITEMS_WRITE if entry.side_effects else PERM_ITEMS_READ
    if fid.startswith("qa."):
        return PERM_ITEMS_WRITE if entry.side_effects else PERM_ITEMS_READ
    if fid.startswith("readiness."):
        return PERM_ITEMS_WRITE if entry.side_effects else PERM_ITEMS_READ
    return None


__all__ = [
    "AuthzSpec",
    "PROJECT",
    "ORG",
    "CONTROL_PLANE",
    "ACTOR_SESSION",
    "CLIENT_LOCAL",
    "DENY",
    "classify",
    "is_explicit_client_local",
    "permission_key_for",
]
