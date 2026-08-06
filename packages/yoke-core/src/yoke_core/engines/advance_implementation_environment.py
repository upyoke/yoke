"""Advance — implementation-entry environment phase.

Automatic ephemeral-env provisioning for the orchestrator at
:mod:`yoke_core.engines.advance_implementation_entry`, for projects
whose ephemeral deploys are push-triggered (``ephemeral-env`` capability
``trigger: "github-push"`` — the GitHub-Actions instantiation of the
shared substrate): push branch, create ``ephemeral_environments`` row,
derive the preview URL from the capability's ``preview_domain``, update
the env row, surface to operator.

Flow-triggered projects (``trigger: "flow"``, e.g. Yoke core-service
previews) deploy through the ``ephemeral-deploy`` flow step_runner
(:mod:`yoke_core.domain.deploy_ephemeral`); provisioning rows at
advance time would create dead ``pending`` previews no push workflow
ever deploys, so those projects skip this phase.

Outcomes returned to the orchestrator (string label + structured
context):

* ``skipped:no-project`` — item carries no project.
* ``skipped:no-capability`` — project has no ``ephemeral-env`` row in
  ``project_capabilities``.
* ``skipped:flow-triggered`` — project's previews deploy via the
  deployment-flow step_runner, not on push.
* ``pending:policy-invalid`` — capability settings are malformed.
* ``provisioned`` — env row created and URL derived.
* ``pending:push-failed`` — branch push to ``origin`` failed; env row
  is NOT created so a later push can drive the normal flow.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional, Tuple

from yoke_core.domain.ephemeral_substrate import (
    EphemeralPolicyError,
    TRIGGER_GITHUB_PUSH,
    load_ephemeral_policy,
    preview_url,
    slugify_branch,
)


def _git_push(repo_root: str, branch: str) -> Tuple[bool, str]:
    proc = subprocess.run(
        ["git", "-C", repo_root, "push", "-u", "origin", branch],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode == 0, (proc.stderr or proc.stdout or "").strip()


def _git_ref_sha(repo_root: str, ref: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", ref],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _item_label(conn, item: Dict[str, Any]) -> str:
    """Public item ref for tracking (falls back to the bare id)."""
    item_id = item.get("id")
    if not item_id:
        return ""
    from yoke_core.domain.project_identity import render_item_ref

    try:
        return render_item_ref(conn, int(item_id))
    except Exception:
        return str(item_id)


def run(
    *,
    item: Dict[str, Any],
    branch: str,
    session_id: str,
    repo_root: str,
    config_root: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Provision the ephemeral environment for the item's project.

    Returns ``(outcome, context)`` for the orchestrator's
    ``AdvancePhaseCompleted`` event.
    """
    del config_root
    project = item.get("project")
    if not project:
        return "skipped:no-project", {}

    from yoke_core.domain.projects_crud import cmd_has_capability
    if not cmd_has_capability(project, "ephemeral-env"):
        return "skipped:no-capability", {"project": project}

    try:
        policy = load_ephemeral_policy(project)
    except EphemeralPolicyError as exc:
        return "pending:policy-invalid", {
            "project": project, "error": str(exc),
        }
    if policy.trigger != TRIGGER_GITHUB_PUSH:
        return "skipped:flow-triggered", {
            "project": project, "trigger": policy.trigger,
        }

    if not repo_root:
        return "pending:no-repo-root", {"project": project}

    push_ok, push_err = _git_push(repo_root, branch)
    if not push_ok:
        return "pending:push-failed", {
            "project": project, "branch": branch, "push_error": push_err,
        }

    from yoke_core.domain.control_plane_transport import (
        local_connection_or_none,
        relay,
    )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ephemeral_env import cmd_create, cmd_update

    conn = local_connection_or_none(connect)
    if conn is not None:
        try:
            item_label = _item_label(conn, item)
            env_id_raw = cmd_create(conn, project, branch, item=item_label)
            try:
                env_id = int(env_id_raw)
            except (TypeError, ValueError):
                return "pending:env-create-failed", {
                    "project": project, "branch": branch, "env_id": env_id_raw,
                }
            slug = slugify_branch(branch)
            url = preview_url(slug, policy.preview_domain)
            deployed_sha = _git_ref_sha(repo_root, branch)
            cmd_update(conn, env_id, "url", url)
            if deployed_sha:
                cmd_update(conn, env_id, "deployed_sha", deployed_sha)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    else:
        # https / no local Postgres: relay CP writes through registered
        # ephemeral_env.* functions — never bare-connect, never YOKE_ENV=.
        item_label = ""
        item_id = item.get("id")
        if item_id:
            item_label = str(item.get("public_ref") or item_id)
        created = relay(
            "ephemeral_env.create",
            {
                "project": str(project),
                "branch": branch,
                "item": item_label,
            },
        )
        env_id = int(created["env_id"])
        slug = slugify_branch(branch)
        url = preview_url(slug, policy.preview_domain)
        deployed_sha = _git_ref_sha(repo_root, branch)
        relay(
            "ephemeral_env.update",
            {"env_id": env_id, "field": "url", "value": url},
        )
        if deployed_sha:
            relay(
                "ephemeral_env.update",
                {
                    "env_id": env_id,
                    "field": "deployed_sha",
                    "value": deployed_sha,
                },
            )

    return "provisioned", {
        "project": project, "branch": branch, "env_id": env_id,
        "url": url, "deployed_sha": deployed_sha,
    }
