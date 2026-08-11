"""Shared QA artifact capture helpers.

Owns the machine-local CAPTURE side of QA artifacts: the scratch-backed
directory the browser daemon writes screenshots into, and run metadata
assembly. Capture scratch is non-durable by design — durability is
opt-in at the QA-evidence boundary, where the recorded row carries a
typed handle (:mod:`yoke_core.domain.qa_artifact_handle`) naming where
the bytes durably live (``s3``) or explicitly declaring machine-locality
(``local``).

There is deliberately no "resolve a stored path against this process's
scratch root" helper anymore: stored references are handles, and a
handle's address comes from ``qa_artifact_handle.handle_address``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from yoke_core.domain import project_scratch_dir
from yoke_core.domain.qa_artifact_handle import (
    QA_ARTIFACT_STORAGE_KIND,
    safe_segment,
)


def artifact_directory(
    project: str,
    subject_id: int | str,
    run_id: int,
    *,
    create: bool = True,
) -> Path:
    """Return the scratch-backed directory for a QA run's captures."""

    return project_scratch_dir.storage_dir(
        QA_ARTIFACT_STORAGE_KIND,
        safe_segment(str(subject_id)),
        str(int(run_id)),
        project=project,
        create=create,
    )


def artifact_file_path(
    project: str,
    subject_id: int | str,
    run_id: int,
    filename: str,
    *,
    create_parent: bool = True,
) -> Path:
    """Return the scratch-backed path for one captured QA artifact file."""

    return project_scratch_dir.storage_path(
        QA_ARTIFACT_STORAGE_KIND,
        safe_segment(str(subject_id)),
        str(int(run_id)),
        safe_segment(filename),
        project=project,
        create_parent=create_parent,
    )


def is_sanctioned_artifact_path(
    path: str | Path,
    project: str,
    subject_id: int | str,
    run_id: int,
) -> bool:
    """Return whether *path* is in this QA run's canonical artifact tree.

    Artifact handles outlive the process that captured them, while the
    scratch path intentionally includes that process's session and run
    identity. Validate the recorded path's complete canonical shape instead
    of rebuilding only the current process's artifact directory.
    """

    candidate = Path(path).expanduser().resolve(strict=False)
    project_root = (
        project_scratch_dir.global_scratch_root()
        / safe_segment(project)
    ).resolve(strict=False)
    try:
        relative = candidate.relative_to(project_root)
    except ValueError:
        return False
    parts = relative.parts
    return (
        len(parts) == 9
        and parts[0] == "sessions"
        and parts[2] == "runs"
        and parts[4] == "storage"
        and parts[5] == QA_ARTIFACT_STORAGE_KIND
        and parts[6] == safe_segment(str(subject_id))
        and parts[7] == str(int(run_id))
    )


def case_artifact_subject(case: dict[str, Any]) -> int | str:
    """Return a collision-safe storage segment for one QA case subject."""
    item_id = case.get("item_id")
    deployment_run_id = case.get("deployment_run_id")
    if item_id is not None and deployment_run_id is None:
        return int(item_id)
    if item_id is None and deployment_run_id is not None:
        return f"deployment-run-{safe_segment(str(deployment_run_id))}"
    raise ValueError("QA case must name exactly one artifact subject")


def build_metadata(
    step_index: int,
    qa_kind: str,
    item_id: int,
    route: str = "/",
    viewport: Optional[Dict[str, int]] = None,
    browser: str = "chromium",
) -> Dict[str, Any]:
    """Build artifact metadata dict."""
    meta: Dict[str, Any] = {
        "step_index": step_index,
        "qa_kind": qa_kind,
        "item_id": item_id,
        "route": route,
    }
    if viewport:
        meta["viewport"] = viewport
    if browser:
        meta["browser"] = browser
    return meta


def route_slug(route: str) -> str:
    """Convert a route path to a slug: strip leading /, replace / with -, lowercase."""
    return route.lstrip("/").replace("/", "-").lower()
