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
    item_id: int,
    run_id: int,
    *,
    create: bool = True,
) -> Path:
    """Return the scratch-backed directory for a QA run's captures."""

    return project_scratch_dir.storage_dir(
        QA_ARTIFACT_STORAGE_KIND,
        str(int(item_id)),
        str(int(run_id)),
        project=project,
        create=create,
    )


def artifact_file_path(
    project: str,
    item_id: int,
    run_id: int,
    filename: str,
    *,
    create_parent: bool = True,
) -> Path:
    """Return the scratch-backed path for one captured QA artifact file."""

    return project_scratch_dir.storage_path(
        QA_ARTIFACT_STORAGE_KIND,
        str(int(item_id)),
        str(int(run_id)),
        safe_segment(filename),
        project=project,
        create_parent=create_parent,
    )


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
