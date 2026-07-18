"""Orchestrate managed-project artifact preview, apply, and drift checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.project_artifacts import PROJECT_ARTIFACT_MANIFEST_REL
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

from .identity import assert_checkout_identity
from .planner import build_plan
from .validate import (
    ProjectArtifactError,
    load_manifest,
    resolve_repo_root,
    validate_bundle,
)
from .writer import apply_plan


def refresh(
    repo_root: str | Path | None,
    *,
    project: str,
    apply: bool = False,
    verify: bool = False,
    source_dev_admin: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Render fresh authority, inspect the checkout, and optionally apply."""

    if apply and verify:
        raise ProjectArtifactError("--apply and --verify are mutually exclusive")
    root = resolve_repo_root(repo_root)
    bundle = _fetch_bundle(
        project,
        source_dev_admin=source_dev_admin,
        session_id=session_id,
    )
    entries = validate_bundle(bundle, source_dev_admin=source_dev_admin)
    assert_checkout_identity(root, bundle)
    operation = "apply" if apply else "verify" if verify else "preview"
    applicable = bundle["applicable"]
    manifest = load_manifest(root) if applicable else None
    plan = (
        build_plan(root, bundle, entries, manifest)
        if applicable
        else _not_applicable_plan()
    )
    report: dict[str, Any] = {
        "operation": operation,
        "project_id": bundle["project_id"],
        "project_slug": bundle["project_slug"],
        "applicable": applicable,
        "applicability_reason": bundle["applicability_reason"],
        "repo_root": str(root),
        "template": bundle["template"],
        "template_version": bundle["template_version"],
        "yoke_version": bundle["yoke_version"],
        "template_source": bundle["template_source"],
        "template_digest": bundle["template_digest"],
        "settings_digest": bundle["settings_digest"],
        "content_digest": bundle["content_digest"],
        "checkout_identity": bundle["checkout_identity"],
        "artifact_policy": bundle["artifact_policy"],
        "manifest": str(root / PROJECT_ARTIFACT_MANIFEST_REL),
        "plan": plan,
        "drift": plan["drift"],
        "conflict_count": len(plan["conflicts"]),
        "applied": False,
        "refused": False,
        "pulumi_stack_config": bundle["pulumi_stack_config"],
    }
    if not applicable:
        report["skipped"] = True
        return report
    if not apply:
        return report
    if plan["conflicts"]:
        report["refused"] = True
        report["refusal_reason"] = (
            "project-owned or locally modified artifacts conflict with the "
            "fresh render; no files were changed"
        )
        return report
    result = apply_plan(root, bundle, entries, manifest, plan)
    report["applied"] = True
    report["apply_result"] = result
    report["drift"] = False
    return report


def _not_applicable_plan() -> dict[str, Any]:
    return {
        "creates": [],
        "updates": [],
        "prunes": [],
        "conflicts": [],
        "unchanged": [],
        "unchanged_count": 0,
        "provenance_changed": False,
        "drift": False,
    }


def _fetch_bundle(
    project: str,
    *,
    source_dev_admin: bool,
    session_id: str | None,
) -> dict[str, Any]:
    # Import here to keep the product CLI importable without yoke-core.  HTTPS
    # clients never need the engine; local self-host mode registers it.
    from yoke_cli.commands._helpers import ensure_handlers_loaded

    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="projects.artifacts.render",
        target=TargetRef(kind="global"),
        payload={
            "project": project,
            "source_dev_admin": source_dev_admin,
        },
        actor=build_actor(session_id=session_id),
        timeout_s=60,
    )
    if not response.success:
        message = (
            response.error.message
            if response.error is not None
            else "artifact render returned success=false"
        )
        raise ProjectArtifactError(message)
    if not isinstance(response.result, dict):
        raise ProjectArtifactError("artifact render returned no bundle object")
    return dict(response.result)


__all__ = ["ProjectArtifactError", "refresh"]
