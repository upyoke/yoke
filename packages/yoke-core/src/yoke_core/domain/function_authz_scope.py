"""Per-function authorization-scope classification for Yoke function dispatch.

Every registered function is sorted into one scope bucket by its *blast radius*.
The dispatch (``check_dispatch_permission``) routes the permission check to the
matching scope:

* ``PROJECT``        — checked against the op's real target project (the project
                       its data belongs to). Tenant content: items, claims,
                       events, qa, a specific project's settings/secrets.
* ``ORG``            — checked against the op's target org (org admin). Org-entity
                       and cross-project registry ops: create a project,
                       deployment flows/runs.
* ``CONTROL_PLANE``  — checked against the ``yoke`` project (yoke admin: the
                       org admin of yoke's org, or yoke's owner). Whole-DB /
                       whole-instance diagnostics: raw db read, doctor.
* ``ACTOR_SESSION``  — the actor operating on its own session/orchestration;
                       allowed for any authenticated actor (the session id binds
                       the work to the caller).
* ``CLIENT_LOCAL``   — machine-local op that writes the *caller's own* ``~/.yoke``
                       config or local checkout; gated by machine possession, not
                       a control-plane permission.
* ``DENY``           — fail-closed: an unclassified *side-effecting* function.

This table is the security spec. The safe default for anything not classified here
is DENY for writes / allow-but-audit for pure reads (see ``classify``).
"""

from __future__ import annotations

from dataclasses import dataclass

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
    PERM_HOOKS_EVALUATE,
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    PERM_ORG_ADMIN,
    PERM_PROJECT_ADMIN,
    PERM_PROJECT_CREATE,
    PERM_PROJECT_INSTALL,
)
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.yoke_function_registry import RegistryEntry

# Scope bucket names (plain strings keep them easy to log + assert on).
PROJECT = "project"
ORG = "org"
CONTROL_PLANE = "control_plane"
ACTOR_SESSION = "actor_session"
CLIENT_LOCAL = "client_local"
DENY = "deny"


@dataclass(frozen=True)
class AuthzSpec:
    """How to authorize one function call."""

    scope: str
    permission_key: str | None  # None when the scope alone decides (local/session/deny)


# --- Explicit classification of the non-PROJECT functions. ---
# function_id -> (scope, permission). PROJECT families are handled by
# permission_key_for and need no entry here.
_BY_ID: dict[str, AuthzSpec] = {
    # Control-plane: whole-DB / whole-instance, gated by yoke admin.
    "db.read.run": AuthzSpec(CONTROL_PLANE, PERM_DB_READ_RAW),
    # Default Doctor is control-plane; yoke_function_permissions routes the
    # HTTPS-safe project quick subset to project read before this fallback.
    "doctor.run.run": AuthzSpec(CONTROL_PLANE, PERM_DB_READ_RAW),
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
    # Registering a NEW project in the org is an org-admin act.
    "projects.create": AuthzSpec(ORG, PERM_PROJECT_CREATE),
    "projects.github_sync_mode.repair": AuthzSpec(
        CONTROL_PLANE,
        PERM_DB_READ_RAW,
    ),
    # Editing an EXISTING project is scoped to that project's admin (the target
    # project resolves from the payload slug/id).
    "projects.update": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    # Per-project settings / secrets / metadata — checked against the TARGET
    # project (resolved from the payload), gated by that project's admin.
    "projects.capability_secret.set": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
    "projects.capability.has": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "projects.get": AuthzSpec(PROJECT, PERM_ITEMS_READ),
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
    "projects.github_binding.status": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "project.snapshot.sync": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "project_structure.command_definitions.get": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "project_structure.command_definitions.list": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "path_claims.conflicts.list": AuthzSpec(PROJECT, PERM_ITEMS_READ),
    "github.pr.create": AuthzSpec(PROJECT, PERM_PROJECT_ADMIN),
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
    "github_actions.variable.get": AuthzSpec(
        PROJECT,
        PERM_GITHUB_ACTIONS_VARIABLE_READ,
    ),
    "conduct.epic_task.update_status": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "conduct.epic.proceed_triage_handoff": AuthzSpec(PROJECT, PERM_ITEMS_WRITE),
    "onboard.checklist.init": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    "onboard.checklist.run": AuthzSpec(PROJECT, PERM_PROJECT_INSTALL),
    # Actor/session: the caller operating on its own session/orchestration.
    "sessions.begin": AuthzSpec(ACTOR_SESSION, None),
    "sessions.touch": AuthzSpec(ACTOR_SESSION, None),
    "sessions.offer": AuthzSpec(ACTOR_SESSION, None),
    "sessions.checkpoint": AuthzSpec(ACTOR_SESSION, None),
    "sessions.checkpoint_read": AuthzSpec(ACTOR_SESSION, None),
    "sessions.ownership_guard": AuthzSpec(ACTOR_SESSION, None),
    "charge.schedule": AuthzSpec(ACTOR_SESSION, None),
    # Machine-local config / repo writes — gated by machine possession.
    "auth.set.run": AuthzSpec(CLIENT_LOCAL, None),
    "connection.set.run": AuthzSpec(CLIENT_LOCAL, None),
    "env.use.run": AuthzSpec(CLIENT_LOCAL, None),
    "config.example.run": AuthzSpec(CLIENT_LOCAL, None),
    "config.stamp_project_env.run": AuthzSpec(CLIENT_LOCAL, None),
    "status.run": AuthzSpec(CLIENT_LOCAL, None),
    "project.register.run": AuthzSpec(CLIENT_LOCAL, None),
    "scratch.dispatch_inputs": AuthzSpec(CLIENT_LOCAL, None),
    # Render-into-checkout / template fetch — local repo writes.
    "agents.render.run": AuthzSpec(CLIENT_LOCAL, None),
    "agents.render.check": AuthzSpec(CLIENT_LOCAL, None),
    "packets.render.run": AuthzSpec(CLIENT_LOCAL, None),
    "packets.check.run": AuthzSpec(CLIENT_LOCAL, None),
    "templates.fetch.run": AuthzSpec(CLIENT_LOCAL, None),
    "templates.list.run": AuthzSpec(CLIENT_LOCAL, None),
    # Intentionally ungated so any authenticated actor can append a field-note.
    "ouroboros.field_note.append": AuthzSpec(CLIENT_LOCAL, None),
}

# Prefix families where every member shares a scope.
_BY_PREFIX: tuple[tuple[str, AuthzSpec], ...] = (
    # Deployment flows/runs reads + run mutation: cross-project infra → org admin.
    ("deployment_flows.", AuthzSpec(ORG, PERM_ORG_ADMIN)),
    ("deployment_runs.", AuthzSpec(ORG, PERM_ORG_ADMIN)),
    # Sign-in admission administration (invites, identity links, auto-join
    # domain) governs who can enter the org → org admin, reads included
    # (invite listings expose member emails).
    ("identity.", AuthzSpec(ORG, PERM_ORG_ADMIN)),
    # GitHub Actions config uses the project's stored GitHub App auth against its repo →
    # project admin on the target project (writes); reads still need the target.
    ("github_actions.", AuthzSpec(PROJECT, PERM_PROJECT_ADMIN)),
    # Project-local install/refresh/uninstall write the caller's own checkout.
    ("project.install", AuthzSpec(CLIENT_LOCAL, None)),
    ("project.refresh", AuthzSpec(CLIENT_LOCAL, None)),
    ("project.uninstall", AuthzSpec(CLIENT_LOCAL, None)),
)


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
    for prefix, prefix_spec in _BY_PREFIX:
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
    ``templates.*``, ``project.install`` family, …) that resolve to a
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
    for prefix, prefix_spec in _BY_PREFIX:
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
    if fid.startswith("items.") or fid.startswith("workflow_item."):
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
    if fid.startswith("strategy."):
        return PERM_ITEMS_WRITE if entry.side_effects else PERM_ITEMS_READ
    if fid.startswith("events."):
        return PERM_EVENTS_WRITE if entry.side_effects else PERM_EVENTS_READ
    if fid.startswith("ephemeral_env."):
        return PERM_ITEMS_WRITE
    if fid.startswith("ouroboros.entry."):
        return PERM_EVENTS_WRITE if entry.side_effects else PERM_EVENTS_READ
    if fid.startswith("ouroboros.wrapup."):
        return PERM_EVENTS_WRITE if entry.side_effects else PERM_EVENTS_READ
    if fid in {"ouroboros.field_note.list", "ouroboros.field_note.get"}:
        return PERM_EVENTS_READ
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
