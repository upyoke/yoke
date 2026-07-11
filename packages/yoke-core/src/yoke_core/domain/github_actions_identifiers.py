"""Validated GitHub Actions identifiers used in REST path segments."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator


_WORKFLOW_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_workflow_identifier(value: str) -> str:
    """Accept one workflow file-name segment or a positive numeric id."""
    selected = str(value or "")
    if selected != selected.strip() or not selected:
        raise ValueError("workflow must be one non-empty path segment")
    if selected.isdigit():
        if int(selected) < 1:
            raise ValueError("numeric workflow id must be positive")
        return selected
    if selected in {".", ".."} or not _WORKFLOW_SEGMENT.fullmatch(selected):
        raise ValueError(
            "workflow must be a single GitHub workflow file-name segment or "
            "positive numeric id"
        )
    return selected


def validate_run_id(value: str) -> str:
    """Accept only positive integer text for a workflow-run path segment."""
    selected = str(value or "")
    if not selected.isdigit() or int(selected) < 1:
        raise ValueError("run_id must be positive integer text")
    return selected


WorkflowIdentifier = Annotated[str, AfterValidator(validate_workflow_identifier)]
WorkflowRunId = Annotated[str, AfterValidator(validate_run_id)]


__all__ = [
    "WorkflowIdentifier",
    "WorkflowRunId",
    "validate_run_id",
    "validate_workflow_identifier",
]
