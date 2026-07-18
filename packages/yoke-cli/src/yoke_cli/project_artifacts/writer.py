"""Apply a fully preflighted project artifact plan."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from yoke_contracts.project_artifacts import (
    PROJECT_ARTIFACT_MANIFEST_REL,
    PROJECT_ARTIFACT_MANIFEST_SCHEMA,
)

from .planner import build_plan
from .validate import ProjectArtifactError, assert_paths_safe


def apply_plan(
    repo_root: Path,
    bundle: Mapping[str, Any],
    entries: list[dict[str, Any]],
    manifest: Mapping[str, Any] | None,
    expected_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-preflight, then atomically replace each file and the manifest."""

    current_plan = build_plan(repo_root, bundle, entries, manifest)
    if _plan_guard(current_plan) != _plan_guard(expected_plan):
        raise ProjectArtifactError(
            "checkout changed after artifact preview; rerun preview before apply"
        )
    if current_plan["conflicts"]:
        raise ProjectArtifactError(
            "artifact apply refused because project-owned conflicts remain"
        )

    by_path = {entry["path"]: entry for entry in entries}
    write_paths = [
        *(change["path"] for change in current_plan["creates"]),
        *(change["path"] for change in current_plan["updates"]),
    ]
    assert_paths_safe(
        repo_root,
        [
            *write_paths,
            *(p["path"] for p in current_plan["prunes"]),
            PROJECT_ARTIFACT_MANIFEST_REL,
        ],
        context="artifact apply",
    )

    written: list[str] = []
    for path in write_paths:
        entry = by_path[path]
        _atomic_write(repo_root / path, entry["content"], entry["mode"])
        written.append(path)
    pruned: list[str] = []
    for change in current_plan["prunes"]:
        target = repo_root / change["path"]
        if target.is_file():
            target.unlink()
            pruned.append(change["path"])
    artifact_manifest = _manifest_from_bundle(bundle, entries)
    manifest_path = repo_root / PROJECT_ARTIFACT_MANIFEST_REL
    _atomic_write(
        manifest_path,
        json.dumps(artifact_manifest, indent=2, sort_keys=True) + "\n",
        0o644,
    )
    return {
        "written": written,
        "pruned": pruned,
        "manifest": str(manifest_path),
    }


def _manifest_from_bundle(
    bundle: Mapping[str, Any], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "manifest_schema": PROJECT_ARTIFACT_MANIFEST_SCHEMA,
        "project_id": bundle["project_id"],
        "project_slug": bundle["project_slug"],
        "template": bundle["template"],
        "template_version": bundle["template_version"],
        "yoke_version": bundle["yoke_version"],
        "template_source": bundle["template_source"],
        "template_digest": bundle["template_digest"],
        "settings_digest": bundle["settings_digest"],
        "content_digest": bundle["content_digest"],
        "checkout_identity": bundle["checkout_identity"],
        "artifact_policy": bundle["artifact_policy"],
        "artifacts": {
            entry["path"]: {
                "sha256": entry["sha256"],
                "mode": entry["mode"],
            }
            for entry in entries
        },
    }


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _plan_guard(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: plan[key]
        for key in (
            "creates",
            "updates",
            "prunes",
            "conflicts",
            "provenance_changed",
            "drift",
        )
    }


__all__ = ["apply_plan"]
