"""Find and remove Codex trust for paths that have been deleted."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.codex_hook_trust_toml import (
    CodexHookTrustStoreError,
    all_hook_entries,
    filter_tables,
    hook_path,
    mutate,
    path_is_gone,
    project_entries,
    read_config,
)
from yoke_contracts.harness_unattended_posture import codex_config_path


@dataclass(frozen=True)
class StaleTrustScan:
    """Trust table keys whose literal filesystem targets are gone."""

    config_path: str
    hook_keys: tuple[str, ...] = ()
    hook_paths: tuple[str, ...] = ()
    project_paths: tuple[str, ...] = ()
    skipped_reason: str = ""

    def payload(self) -> dict[str, object]:
        return {
            "config_path": self.config_path,
            "stale_hook_entries": len(self.hook_keys),
            "stale_hook_paths": len(self.hook_paths),
            "stale_project_entries": len(self.project_paths),
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True)
class TrustMutation:
    """Count-only receipt for one config mutation."""

    config_path: str
    hook_entries_removed: int = 0
    hook_entries_written: int = 0
    project_entries_removed: int = 0
    stale_hook_paths: int = 0
    changed: bool = False
    dry_run: bool = False
    skipped_reason: str = ""

    def payload(self) -> dict[str, object]:
        return {
            "config_path": self.config_path,
            "hook_entries_removed": self.hook_entries_removed,
            "hook_entries_written": self.hook_entries_written,
            "project_entries_removed": self.project_entries_removed,
            "stale_hook_paths": self.stale_hook_paths,
            "changed": self.changed,
            "dry_run": self.dry_run,
            "skipped_reason": self.skipped_reason,
        }


def stale_trust_scan(*, config_path: Optional[Path] = None) -> StaleTrustScan:
    """Resolve every deleted literal path without changing the config."""
    selected = config_path or codex_config_path()
    if not selected.exists():
        return StaleTrustScan(str(selected), skipped_reason="Codex config is absent")
    if not selected.is_file():
        raise CodexHookTrustStoreError(
            f"Codex config is not a regular file: {selected}"
        )
    _, document = read_config(selected)
    hook_keys = tuple(
        sorted(
            key
            for key in all_hook_entries(document)
            if (path := hook_path(key)) is not None and path_is_gone(path)
        )
    )
    hook_paths = tuple(
        sorted({hook_path(key) for key in hook_keys if hook_path(key)})
    )
    project_paths = tuple(
        sorted(path for path in project_entries(document) if path_is_gone(path))
    )
    return StaleTrustScan(str(selected), hook_keys, hook_paths, project_paths)


def sweep_stale_trust(
    *, config_path: Optional[Path] = None, dry_run: bool = False
) -> TrustMutation:
    """Drop only trust tables whose literal filesystem paths are gone."""
    selected = config_path or codex_config_path()
    scan = stale_trust_scan(config_path=selected)
    if scan.skipped_reason:
        return TrustMutation(
            str(selected), dry_run=dry_run, skipped_reason=scan.skipped_reason
        )

    def plan(text: str, _document: dict[str, Any]) -> tuple[str, TrustMutation]:
        updated, hook_count, project_count = filter_tables(
            text, set(scan.hook_keys), set(scan.project_paths)
        )
        if hook_count != len(scan.hook_keys) or project_count != len(
            scan.project_paths
        ):
            raise CodexHookTrustStoreError(
                "stale trust uses an unsupported inline TOML layout"
            )
        return updated, TrustMutation(
            str(selected),
            hook_entries_removed=hook_count,
            project_entries_removed=project_count,
            stale_hook_paths=len(scan.hook_paths),
            changed=bool(hook_count or project_count),
            dry_run=dry_run,
        )

    if dry_run:
        text, document = read_config(selected)
        return plan(text, document)[1]
    return mutate(selected, plan)
