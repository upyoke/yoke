"""Own Codex's path-keyed hook trust for Yoke-installed checkouts.

Codex stores one normalized handler hash per literal ``hooks.json`` path in
its user ``config.toml``.  Project install may mint those hashes because Yoke
authored the file; linked worktrees may only mirror an already trusted source.
This module also removes retired lane entries and sweeps entries whose paths
no longer exist, while preserving every unrelated TOML byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.codex_hook_trust import (
    CodexHookIdentityError,
    codex_hook_hashes,
)
from yoke_contracts.codex_hook_trust_toml import (
    CodexHookTrustStoreError,
    TRUSTED_HASH_KEY,
    all_hook_entries as _all_hook_entries,
    append_hook_entries as _append_hook_entries,
    entries_for,
    filter_tables as _filter_tables,
    hook_path as _hook_path,
    mutate as _mutate,
    path_is_gone as _path_is_gone,
    project_entries as _project_entries,
    read_config as _read_config,
    read_trust_state,
)
from yoke_contracts.harness_unattended_posture import codex_config_path


HOOKS_RELATIVE_PATH = Path(".codex/hooks.json")
SWEEP_COMMAND = "yoke codex hook-trust sweep"


@dataclass(frozen=True)
class HookFileTrust:
    """Exact persisted-vs-current standing for one hooks file."""

    hooks_path: str
    expected: tuple[str, ...] = ()
    trusted: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    blocked_reason: str = ""

    @property
    def approved(self) -> bool:
        return bool(self.expected) and not (
            self.blocked_reason or self.missing or self.modified or self.extra
        )

    def summary(self) -> str:
        if self.approved:
            return f"{len(self.trusted)} hook entries trusted"
        if self.blocked_reason:
            return self.blocked_reason
        parts = []
        if self.missing:
            parts.append(f"{len(self.missing)} untrusted: {', '.join(self.missing)}")
        if self.modified:
            parts.append(f"{len(self.modified)} modified: {', '.join(self.modified)}")
        if self.extra:
            parts.append(f"{len(self.extra)} retired: {', '.join(self.extra)}")
        return "; ".join(parts) or "no normalized hook handlers"


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


def hooks_file_for(checkout: str | Path) -> Path:
    return Path(checkout).expanduser() / HOOKS_RELATIVE_PATH


def retrust_recovery(checkout: str | Path) -> str:
    return f"re-trust in Codex: open Codex in {Path(checkout)}, Hooks, Trust"


def inspect_hook_file_trust(
    hooks_path: Path, *, config_path: Optional[Path] = None
) -> HookFileTrust:
    """Compare one current hooks file with its exact persisted trust set."""
    selected = config_path or codex_config_path()
    try:
        expected = codex_hook_hashes(hooks_path)
    except CodexHookIdentityError as exc:
        return HookFileTrust(str(hooks_path), blocked_reason=str(exc))
    state, reason = read_trust_state(selected)
    if reason:
        return HookFileTrust(
            str(hooks_path), tuple(sorted(expected)), blocked_reason=reason
        )
    persisted = entries_for(state, hooks_path)
    trusted = tuple(
        sorted(key for key, digest in expected.items() if persisted.get(key) == digest)
    )
    return HookFileTrust(
        str(hooks_path),
        expected=tuple(sorted(expected)),
        trusted=trusted,
        missing=tuple(sorted(set(expected) - set(persisted))),
        modified=tuple(
            sorted(
                key
                for key in set(expected) & set(persisted)
                if expected[key] != persisted[key]
            )
        ),
        extra=tuple(sorted(set(persisted) - set(expected))),
    )


def mint_installed_checkout_trust(
    checkout: str | Path, *, config_path: Optional[Path] = None
) -> TrustMutation:
    """Replace one Yoke-installed checkout's trust with current hashes."""
    hooks_path = hooks_file_for(checkout)
    selected = config_path or codex_config_path()
    if not hooks_path.is_file():
        return TrustMutation(
            str(selected), skipped_reason=f"Codex hooks file is absent: {hooks_path}"
        )
    try:
        selected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise CodexHookTrustStoreError(f"could not prepare {selected}: {exc}") from exc
    try:
        expected = codex_hook_hashes(hooks_path)
    except CodexHookIdentityError as exc:
        raise CodexHookTrustStoreError(
            f"could not normalize {hooks_path}: {exc}"
        ) from exc

    def plan(text: str, document: dict[str, Any]) -> tuple[str, TrustMutation]:
        state = _all_hook_entries(document)
        existing = {key for key in state if _hook_path(key) == str(hooks_path)}
        current = entries_for(
            {
                key: str(value.get(TRUSTED_HASH_KEY) or "")
                for key, value in state.items()
                if isinstance(value, dict)
            },
            hooks_path,
        )
        if current == expected and len(existing) == len(expected):
            return text, TrustMutation(str(selected))
        filtered, hook_count, _ = _filter_tables(text, existing, set())
        if hook_count != len(existing):
            raise CodexHookTrustStoreError(
                "hook trust uses an unsupported inline TOML layout"
            )
        updated = _append_hook_entries(filtered, hooks_path, expected)
        return updated, TrustMutation(
            str(selected),
            hook_entries_removed=hook_count,
            hook_entries_written=len(expected),
            changed=True,
        )

    return _mutate(selected, plan)


def remove_checkout_trust(
    checkout: str | Path, *, config_path: Optional[Path] = None
) -> TrustMutation:
    """Remove hook and folder trust for one retired checkout or worktree."""
    selected = config_path or codex_config_path()
    if not selected.exists():
        return TrustMutation(str(selected), skipped_reason="Codex config is absent")
    if not selected.is_file():
        raise CodexHookTrustStoreError(
            f"Codex config is not a regular file: {selected}"
        )
    checkout_key = str(Path(checkout).expanduser())
    hooks_path = str(hooks_file_for(checkout_key))

    def plan(text: str, document: dict[str, Any]) -> tuple[str, TrustMutation]:
        hook_keys = {
            key for key in _all_hook_entries(document) if _hook_path(key) == hooks_path
        }
        projects = (
            {checkout_key} if checkout_key in _project_entries(document) else set()
        )
        updated, hook_count, project_count = _filter_tables(text, hook_keys, projects)
        if hook_count != len(hook_keys) or project_count != len(projects):
            raise CodexHookTrustStoreError(
                "path trust uses an unsupported inline TOML layout"
            )
        return updated, TrustMutation(
            str(selected),
            hook_entries_removed=hook_count,
            project_entries_removed=project_count,
            changed=bool(hook_count or project_count),
        )

    return _mutate(selected, plan)


def stale_trust_scan(*, config_path: Optional[Path] = None) -> StaleTrustScan:
    """Resolve every deleted literal path without changing the config."""
    selected = config_path or codex_config_path()
    if not selected.exists():
        return StaleTrustScan(str(selected), skipped_reason="Codex config is absent")
    if not selected.is_file():
        raise CodexHookTrustStoreError(
            f"Codex config is not a regular file: {selected}"
        )
    _, document = _read_config(selected)
    hook_keys = tuple(
        sorted(
            key
            for key in _all_hook_entries(document)
            if (path := _hook_path(key)) is not None and _path_is_gone(path)
        )
    )
    hook_paths = tuple(
        sorted({_hook_path(key) for key in hook_keys if _hook_path(key)})
    )
    project_paths = tuple(
        sorted(path for path in _project_entries(document) if _path_is_gone(path))
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
        updated, hook_count, project_count = _filter_tables(
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
        text, document = _read_config(selected)
        return plan(text, document)[1]
    return _mutate(selected, plan)


def worktree_cleanup_warning(worktree: str | Path) -> str:
    """Best-effort teardown warning with the exact recovery command."""
    try:
        remove_checkout_trust(worktree)
    except CodexHookTrustStoreError as exc:
        return (
            f"CodexWorktreeTrustCleanupFailed for {worktree}: {exc}. "
            f"Recovery: run `{SWEEP_COMMAND}`."
        )
    return ""


__all__ = [
    "CodexHookTrustStoreError",
    "HOOKS_RELATIVE_PATH",
    "HookFileTrust",
    "SWEEP_COMMAND",
    "StaleTrustScan",
    "TRUSTED_HASH_KEY",
    "TrustMutation",
    "entries_for",
    "hooks_file_for",
    "inspect_hook_file_trust",
    "mint_installed_checkout_trust",
    "read_trust_state",
    "remove_checkout_trust",
    "retrust_recovery",
    "stale_trust_scan",
    "sweep_stale_trust",
    "worktree_cleanup_warning",
]
