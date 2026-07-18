"""Read-only project artifact reconciliation planning."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.project_artifacts import PROJECT_ARTIFACT_MANIFEST_REL

from .validate import (
    ProjectArtifactError,
    assert_targets_plannable,
    sha256_bytes,
)


def build_plan(
    repo_root: Path,
    bundle: Mapping[str, Any],
    entries: list[dict[str, Any]],
    manifest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the exact create/update/prune/conflict plan without mutation."""

    prior = manifest or {}
    _assert_project_lineage(bundle, prior)
    old_records = dict(prior.get("artifacts") or {})
    desired = {entry["path"]: entry for entry in entries}
    all_paths = sorted(set(old_records) | set(desired))
    assert_targets_plannable(repo_root, [*all_paths, PROJECT_ARTIFACT_MANIFEST_REL])

    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    prunes: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    unchanged: list[str] = []

    for path in sorted(desired):
        wanted = desired[path]
        current = file_state(repo_root / path)
        old = old_records.get(path)
        if current is None:
            creates.append(_change(path, "absent", None, wanted))
            continue
        if current["sha256"] == wanted["sha256"]:
            if current["mode"] == wanted["mode"]:
                unchanged.append(path)
                continue
            if old and _matches_record(current, old):
                updates.append(_change(path, "mode_drift", current, wanted))
            else:
                conflicts.append(
                    _conflict(path, "unowned_or_modified_mode", current, wanted)
                )
            continue
        if old and _matches_record(current, old):
            updates.append(
                _change(path, "template_or_settings_changed", current, wanted)
            )
            continue
        conflicts.append(
            _conflict(
                path,
                "locally_modified" if old else "unowned_existing",
                current,
                wanted,
            )
        )

    for path in sorted(set(old_records) - set(desired)):
        current = file_state(repo_root / path)
        if current is None:
            continue
        if _matches_record(current, old_records[path]):
            prunes.append(
                {
                    "path": path,
                    "reason": "left_rendered_artifact_set",
                    "current_sha256": current["sha256"],
                    "current_mode": current["mode"],
                }
            )
        else:
            conflicts.append(
                {
                    "path": path,
                    "reason": "modified_artifact_left_rendered_set",
                    "current_sha256": current["sha256"],
                    "current_mode": current["mode"],
                    "managed_sha256": old_records[path]["sha256"],
                    "managed_mode": old_records[path]["mode"],
                }
            )

    provenance_changed = _provenance_changed(bundle, prior)
    drift = bool(creates or updates or prunes or conflicts or provenance_changed)
    return {
        "creates": creates,
        "updates": updates,
        "prunes": prunes,
        "conflicts": conflicts,
        "unchanged": unchanged,
        "unchanged_count": len(unchanged),
        "provenance_changed": provenance_changed,
        "drift": drift,
    }


def file_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    return {
        "sha256": sha256_bytes(data),
        "mode": stat.S_IMODE(path.stat().st_mode),
    }


def _matches_record(current: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    return current["sha256"] == record.get("sha256") and current["mode"] == record.get(
        "mode"
    )


def _change(
    path: str,
    reason: str,
    current: Mapping[str, Any] | None,
    wanted: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "path": path,
        "reason": reason,
        "current_sha256": current["sha256"] if current else None,
        "current_mode": current["mode"] if current else None,
        "desired_sha256": wanted["sha256"],
        "desired_mode": wanted["mode"],
    }


def _conflict(
    path: str,
    reason: str,
    current: Mapping[str, Any],
    wanted: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "path": path,
        "reason": reason,
        "current_sha256": current["sha256"],
        "current_mode": current["mode"],
        "desired_sha256": wanted["sha256"],
        "desired_mode": wanted["mode"],
    }


def _assert_project_lineage(
    bundle: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    if not manifest:
        return
    if manifest.get("project_id") != bundle.get("project_id"):
        raise ProjectArtifactError(
            "artifact manifest belongs to a different project id"
        )
    if manifest.get("project_slug") != bundle.get("project_slug"):
        raise ProjectArtifactError(
            "artifact manifest belongs to a different project slug"
        )


def _provenance_changed(bundle: Mapping[str, Any], manifest: Mapping[str, Any]) -> bool:
    if not manifest:
        return True
    return any(
        manifest.get(key) != bundle.get(key)
        for key in (
            "template_version",
            "yoke_version",
            "template_source",
            "template_digest",
            "settings_digest",
            "content_digest",
            "checkout_identity",
            "artifact_policy",
        )
    )


__all__ = ["build_plan", "file_state"]
