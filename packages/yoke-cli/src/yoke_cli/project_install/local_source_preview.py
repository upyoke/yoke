"""Read-only planning and preservation for local-source refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.project_install import files as files_layer
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.project_install.preflight import preflight_apply


def preview_report(
    root: Path,
    bundle: dict[str, Any],
    *,
    prior_manifest: dict[str, Any],
    manifest_source: str,
    source_label: str,
    preserved_files: dict[str, str],
) -> dict[str, Any]:
    preflight = preflight_apply(
        root, bundle, prior_manifest, preserved_files,
    )
    bundle_files = bundle["files"]
    files_layer.assert_safe_bundle_paths(entry["path"] for entry in bundle_files)
    new_hashes = {
        entry["path"]: files_layer.sha256_text(entry["content"])
        for entry in bundle_files
    }
    would_write = []
    for entry in bundle_files:
        target = root / entry["path"]
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current = None
        if (
            current is None
            or files_layer.sha256_text(current) != new_hashes[entry["path"]]
        ):
            would_write.append(entry["path"])
    would_prune: list[str] = []
    would_preserve: list[str] = []
    old_files = dict(prior_manifest.get("files") or {})
    keep_paths = set(new_hashes) | set(preserved_files)
    for rel in sorted(set(old_files) - keep_paths):
        target = root / rel
        if not target.is_file():
            continue
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current = None
        if (
            current is not None
            and files_layer.sha256_text(current) == old_files[rel]
        ):
            would_prune.append(rel)
        else:
            would_preserve.append(rel)
    hook_plans = preflight["hook_plans"]
    hooks_would_add = {
        rel: plan["added"]
        for rel, plan in hook_plans.items()
        if plan["added"]
    }
    hooks_would_remove = {
        rel: plan["removed"]
        for rel, plan in hook_plans.items()
        if plan["removed"]
    }
    settings_would_create = sorted(
        rel for rel, plan in hook_plans.items() if plan["created"]
    )
    settings_would_delete = sorted(
        rel for rel, plan in hook_plans.items() if plan["deleted_file"]
    )
    git_hook_preview = preflight["git_hook_preview"]
    worktrees_ignore = dict(preflight["worktrees_ignore"])
    worktrees_ignore["owned_by_install"] = bool(
        prior_manifest.get("worktrees_ignore_added")
    )
    worktrees_ignore["would_add"] = not worktrees_ignore["present"]
    return {
        "operation": "refresh",
        "mode": "copy",
        "repo_root": str(root),
        "project_id": bundle["project_id"],
        "project_slug": bundle["project_slug"],
        "yoke_version": bundle["yoke_version"],
        "source": source_label,
        "source_checkout": source_label.split(":", 1)[1],
        "source_dev_admin": True,
        "preview": True,
        "apply_required": True,
        "target_writes": False,
        "server_state_writes": False,
        "manifest_source": manifest_source,
        "prior_contract_records_discarded": list(
            prior_manifest.get(
                files_layer.DISCARDED_PRIOR_CONTRACT_RECORDS_KEY
            ) or []
        ),
        "prior_strategy_records_discarded": list(
            prior_manifest.get(
                files_layer.DISCARDED_PRIOR_STRATEGY_RECORDS_KEY
            ) or []
        ),
        "files_would_write": would_write,
        "files_would_prune": would_prune,
        "files_would_preserve_modified": would_preserve,
        "files_preserved_unrendered": sorted(preserved_files),
        "files_unchanged": (
            len(new_hashes) - len(would_write) + len(preserved_files)
        ),
        "hooks_would_add": hooks_would_add,
        "hooks_would_remove": hooks_would_remove,
        "settings_files_would_create": settings_would_create,
        "settings_files_would_delete": settings_would_delete,
        "git_hooks_would_install_or_update": (
            git_hook_preview.installed + git_hook_preview.updated
        ),
        "git_hook_actions": git_hook_preview.actions,
        "worktrees_ignore": worktrees_ignore,
        "snapshot_sync": {
            "status": "skipped",
            "reason": "preview performs no external or server snapshot writes",
        },
        "machine_config_newly_registered": False,
        "warnings": git_hook_preview.warnings,
    }


def preserved_manifest_files(
    root: Path,
    bundle: dict[str, Any],
    prior_manifest: dict[str, Any],
) -> dict[str, str]:
    """Carry server-rendered managed files outside local source namespaces."""
    raw_prefixes = bundle.get("source_managed_prefixes")
    if not isinstance(raw_prefixes, list) or not all(
        isinstance(prefix, str) and prefix for prefix in raw_prefixes
    ):
        raise ProjectInstallError(
            "source bundle does not declare source_managed_prefixes"
        )
    rendered = {str(entry["path"]) for entry in bundle["files"]}
    preserved: dict[str, str] = {}
    old_files = dict(prior_manifest.get("files") or {})
    for raw_path, raw_hash in sorted(old_files.items()):
        path = str(raw_path)
        source_managed = any(path.startswith(prefix) for prefix in raw_prefixes)
        if path in rendered or source_managed:
            continue
        if (root / path).is_file():
            preserved[path] = str(raw_hash)
    files_layer.assert_safe_bundle_paths(preserved)
    return preserved


__all__ = ["preserved_manifest_files", "preview_report"]
