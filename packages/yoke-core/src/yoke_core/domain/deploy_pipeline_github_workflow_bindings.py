"""Declarative external-project input bindings for github-actions-workflow stages.

A stage may declare ``input_bindings``: placeholders resolved from another
registered project's branch tip rather than this run's own head_sha/run_id/
target_environment. Recovering a prior durable dispatch's already-bound
values is mandatory before any fresh resolution, so a retry (lost response,
process restart, a rejected attempt retried under the same request id) can
never dispatch a changed pair under the same logical request — only a
missing intent, or an explicit fresh retrigger (its own, empty-recovery
request id), resolves anew. A rejected intent still recovers: rejection
means GitHub refused the POST and another POST attempt is safe, not that
the payload itself may now differ. Project identity (which project, which
branch) is declared in the stage's own config; this module only knows the
generic lookup shape.
"""

from __future__ import annotations

from typing import Dict, Mapping, Tuple

from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    RESERVED_INPUT_PLACEHOLDERS,
)
from yoke_core.domain.deploy_pipeline_reporting import _run_cmd


def resolve_branch_head_sha(repo_path: str, branch: str) -> Tuple[str, str]:
    """The exact commit ``branch`` currently names in the checkout at ``repo_path``.

    A plain git remote read — no GitHub App or Yoke API authority needed,
    the same mechanism already relied on to resolve a product's publish SHA.
    """
    result = _run_cmd(
        ["git", "-C", repo_path, "ls-remote", "origin", f"refs/heads/{branch}"]
    )
    sha = ""
    if result.returncode == 0 and result.stdout.strip():
        sha = result.stdout.split()[0].strip()
    if not sha:
        return "", (
            f"could not resolve branch '{branch}' at '{repo_path}' via git "
            "ls-remote; missing reach fails the stage rather than binding "
            "a stale or empty value"
        )
    return sha, ""


def resolve_declared_input_bindings(
    bindings: Mapping[str, Mapping[str, str]],
    *,
    request_id: str,
) -> Tuple[Dict[str, str], str]:
    """Resolve declared external input bindings for one stage dispatch.

    Each binding names an external project's branch tip, e.g.
    ``{"consumer_sha": {"project": "platform", "branch": "main"}}``. Returns
    ``(resolved, error)``; error is non-empty and resolved is empty when any
    binding's authority is unavailable.
    """
    if not bindings:
        return {}, ""
    reserved = RESERVED_INPUT_PLACEHOLDERS & set(bindings)
    if reserved:
        return {}, (
            f"input binding name(s) {sorted(reserved)} collide with the "
            "built-in head_sha/run_id/target_environment placeholders"
        )
    if request_id:
        from yoke_core.domain.github_workflow_dispatch_intents import (
            DispatchIntentStoreError,
            latest_intent,
        )

        try:
            intent = latest_intent(request_id)
        except DispatchIntentStoreError as exc:
            return {}, f"could not read a prior dispatch intent: {exc}"
        if intent is not None:
            # Recover regardless of state, rejected included: rejection
            # means GitHub refused the POST and a retry may attempt it
            # again, not that the bound values themselves are now stale.
            # A caller that genuinely wants a different pair uses the
            # explicit --fresh retrigger, which mints its own request id
            # and never reaches this branch (request_id is empty for it).
            recovered = {key: intent.inputs.get(key, "") for key in bindings}
            if all(recovered.values()):
                return recovered, ""
            # A durable dispatch intent already exists for this exact
            # logical request but does not record every declared binding —
            # an unexpected shape, not an absent one. Resolving fresh here
            # would risk dispatching a changed pair under the same request
            # id; fail closed instead of rebinding it.
            return {}, (
                f"a dispatch intent already exists for {request_id!r} but "
                f"does not record all declared bindings {sorted(bindings)}; "
                "refusing to rebind it"
            )

    from yoke_core.domain.deploy_pipeline_run_context import (
        resolve_project_checkout_path,
    )

    resolved: Dict[str, str] = {}
    for key, binding in bindings.items():
        project = str(binding.get("project") or "")
        branch = str(binding.get("branch") or "")
        if not project or not branch:
            return {}, f"input binding '{key}' is missing project/branch"
        repo_path = resolve_project_checkout_path(project)
        if not repo_path:
            return {}, (
                f"no machine-config checkout is registered for project "
                f"'{project}'; register one to resolve its '{branch}' head "
                "(yoke project register <checkout> --project-id N)"
            )
        sha, error = resolve_branch_head_sha(repo_path, branch)
        if error:
            return {}, error
        resolved[key] = sha
    return resolved, ""


__all__ = [
    "resolve_branch_head_sha",
    "resolve_declared_input_bindings",
]
