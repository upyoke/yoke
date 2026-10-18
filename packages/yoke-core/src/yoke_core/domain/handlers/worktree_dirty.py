"""Read dirty-file classifications from a machine-mapped project checkout."""

from __future__ import annotations

import subprocess

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.classify_dirty_files import classify_dirty_files
from yoke_core.domain.project_checkout_locations import checkout_for_project_slug


class ClassifyDirtyRequest(BaseModel):
    project: str = Field(min_length=1)
    exclude_worktrees: bool = False


class ClassifyDirtyResponse(BaseModel):
    project: str
    checkout: str
    yoke_managed: list[str]
    user_authored: list[str]


def _refuse(code: str, message: str, recovery: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, recovery_hint=recovery),
    )


def handle_classify_dirty(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        spec = ClassifyDirtyRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _refuse(
            "payload_invalid",
            str(exc),
            "See `yoke worktree classify-dirty --help`.",
        )
    try:
        checkout = checkout_for_project_slug(spec.project)
    except Exception as exc:
        return _refuse(
            "project_checkout_unavailable",
            str(exc),
            "Repair this machine's project mapping with `yoke project register --help`.",
        )
    if checkout is None:
        return _refuse(
            "project_checkout_unavailable",
            f"Project {spec.project!r} could not resolve to a machine-local checkout.",
            "Check `yoke projects get PROJECT` and register its checkout with "
            "`yoke project register CHECKOUT --project-id ID`.",
        )
    # The shared classifier tolerates git failures for its engine callers.
    # This admission read must prove the checkout readable before using it.
    try:
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        managed, authored = classify_dirty_files(
            repo_path=str(checkout),
            exclude_worktrees=spec.exclude_worktrees,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _refuse(
            "dirty_classification_failed",
            f"Could not inspect {checkout}: {exc}",
            "Restore Git access to the mapped checkout, then rerun "
            "`yoke worktree classify-dirty --project PROJECT` before merging.",
        )
    return HandlerOutcome(
        result_payload={
            "project": spec.project,
            "checkout": str(checkout),
            "yoke_managed": managed,
            "user_authored": authored,
        }
    )
