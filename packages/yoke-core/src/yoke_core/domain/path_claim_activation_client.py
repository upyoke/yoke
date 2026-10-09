"""Resolve machine-local integration heads before relaying claim activation."""

from __future__ import annotations

from typing import Callable

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)


_RECOVERY = "Resolve the reported claim blocker or integration ref, then retry activation-run on the machine holding the project's registered checkout."


def _refuse(code: str, message: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function="claims.path.activation_run",
        version="v1",
        error=FunctionError(code=code, message=message, recovery_hint=_RECOVERY),
    )


def local_checkout(target: TargetRef, dispatch: Callable) -> str | None:
    from yoke_core.domain.project_checkout_locations import checkout_for_project_id

    detail = dispatch(function_id="items.detail.get", target=target, payload={})
    if not detail.success:
        return None
    project = ((detail.result or {}).get("item") or {}).get("project") or {}
    project_id = project.get("id")
    checkout = (
        checkout_for_project_id(int(project_id)) if project_id is not None else None
    )
    return str(checkout) if checkout is not None else None


def run_activation(
    target: TargetRef,
    *,
    dispatch: Callable,
    checkout_for_item: Callable[[], str | None] | None = None,
) -> FunctionCallResponse:
    """Share client-git/server-state activation across CLI and worktree entry."""
    from yoke_core.domain.advance_path_claim_activation_retry import (
        resolve_integration_head_with_retry,
    )

    listed = dispatch(
        function_id="claims.path.list",
        target=target,
        payload={"states": ["planned", "blocked"]},
    )
    if not listed.success:
        return listed
    claims = (listed.result or {}).get("claims") or []
    resolved_heads: dict[int, str] = {}
    if claims:
        checkout = (
            checkout_for_item()
            if checkout_for_item
            else local_checkout(target, dispatch)
        )
        if checkout is None:
            return _refuse(
                "path_claim_checkout_missing",
                "claim's item has no machine-local checkout mapping; cannot resolve integration head. "
                "Register the project's checkout with yoke project register <checkout> --project-id <id>.",
            )
        for claim in claims:
            rr = resolve_integration_head_with_retry(
                None,
                project_id="",
                repo_path=checkout,
                integration_target=str(claim.get("integration_target") or "main"),
            )
            if rr.error is not None:
                if str(claim.get("state")) == "planned":
                    return _refuse("path_claim_head_resolution_failed", rr.error)
                continue
            resolved_heads[int(claim["id"])] = str(rr.commit_sha)

    run = dispatch(
        function_id="claims.path.activation_run",
        target=target,
        payload={"resolved_heads": resolved_heads},
    )
    if not run.success:
        return run
    result = run.result or {}
    errors = [str(e) for e in result.get("blocked_errors") or []]
    if result.get("diverged_error"):
        errors.append(str(result["diverged_error"]))
    for outcome in result.get("outcomes") or []:
        if outcome.get("error"):
            errors.append(str(outcome["error"]))
        elif (
            outcome.get("state_before") == "planned"
            and outcome.get("state_after") != "active"
        ):
            errors.append(
                f"claim {outcome['claim_id']} remains {outcome.get('state_after')}"
            )
    if errors:
        return run.model_copy(
            update={
                "success": False,
                "error": FunctionError(
                    code="path_claim_activation_incomplete",
                    message="\n".join(dict.fromkeys(errors)),
                    recovery_hint=_RECOVERY,
                ),
            }
        )
    return run
