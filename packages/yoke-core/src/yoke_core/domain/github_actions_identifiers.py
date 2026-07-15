"""Validation and URL quoting for GitHub Actions repository config paths."""

from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import quote

from pydantic import AfterValidator


REPO_SLUG_PATTERN = (
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
    r"/[A-Za-z0-9_.-]{1,100}$"
)
CONFIG_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,99}$"

_REPO_SLUG_RE = re.compile(REPO_SLUG_PATTERN)
_CONFIG_NAME_RE = re.compile(CONFIG_NAME_PATTERN)
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


def repository_api_path(repo: str) -> str:
    """Return a validated, segment-quoted ``/repos/owner/name`` path."""
    if _REPO_SLUG_RE.fullmatch(repo) is None:
        raise ValueError("GitHub repository must be a canonical owner/name slug")
    owner, name = repo.split("/", 1)
    if name in {".", ".."}:
        raise ValueError("GitHub repository name is not canonical")
    return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def config_name_path(name: str) -> str:
    """Return one validated, URL-quoted Actions secret/variable name."""
    if _CONFIG_NAME_RE.fullmatch(name) is None:
        raise ValueError(
            "GitHub Actions config name must start with a letter or underscore "
            "and contain only letters, digits, and underscores"
        )
    return quote(name, safe="")


__all__ = [
    "CONFIG_NAME_PATTERN", "REPO_SLUG_PATTERN", "config_name_path",
    "repository_api_path", "validate_run_id", "validate_workflow_identifier",
    "WorkflowIdentifier", "WorkflowRunId",
]
