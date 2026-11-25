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
from yoke_contracts.codex_hook_trust_sweep import (
    StaleTrustScan,
    TrustMutation,
    stale_trust_scan,
    sweep_stale_trust,
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
    project_entries as _project_entries,
    read_trust_state,
)
from yoke_contracts.harness_unattended_posture import codex_config_path
from yoke_contracts.harness_folder_trust import codex_path_spellings


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


def hooks_file_for(checkout: str | Path) -> Path:
    return Path(checkout).expanduser() / HOOKS_RELATIVE_PATH


def retrust_recovery(checkout: str | Path, *, lane: bool = False) -> str:
    if lane:
        repair = (
            "Restore the lane's hooks to the trusted source content, then run "
            "`yoke doctor run --only harness-setup --fix`. "
            "If you intend to keep different hooks, "
        )
    else:
        repair = f"Run `yoke project refresh` in {Path(checkout)}. If needed, "
    return f"{repair}re-trust in Codex: open Codex in {Path(checkout)}, Hooks, Trust"


def inspect_hook_file_trust(
    hooks_path: Path,
    *,
    config_path: Optional[Path] = None,
    spellings: Optional[tuple[str, ...]] = None,
) -> HookFileTrust:
    """Compare current hashes with the persisted set for each literal path."""
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
    paths = spellings or codex_path_spellings(hooks_path)
    if len(paths) == 1:
        persisted = entries_for(state, Path(paths[0]))
    else:
        expected = {
            f"{path}:{key}": digest for path in paths for key, digest in expected.items()
        }
        persisted = {
            f"{path}:{key}": digest
            for path in paths
            for key, digest in entries_for(state, Path(path)).items()
        }
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
    if not selected.parent.is_dir():
        return TrustMutation(str(selected), skipped_reason="codex_not_installed")
    try:
        expected = codex_hook_hashes(hooks_path)
    except CodexHookIdentityError as exc:
        raise CodexHookTrustStoreError(
            f"could not normalize {hooks_path}: {exc}"
        ) from exc
    paths = codex_path_spellings(hooks_path)

    def plan(text: str, document: dict[str, Any]) -> tuple[str, TrustMutation]:
        state = _all_hook_entries(document)
        existing = {key for key in state if _hook_path(key) in paths}
        wanted = {
            f"{path}:{key}": digest for path in paths for key, digest in expected.items()
        }
        current = {
            key: state[key].get(TRUSTED_HASH_KEY)
            for key in existing
            if isinstance(state[key], dict)
        }
        if current == wanted and existing == wanted.keys():
            return text, TrustMutation(str(selected))
        filtered, hook_count, _ = _filter_tables(text, existing, set())
        if hook_count != len(existing):
            raise CodexHookTrustStoreError(
                "hook trust uses an unsupported inline TOML layout"
            )
        updated = filtered
        for path in paths:
            updated = _append_hook_entries(updated, Path(path), expected)
        return updated, TrustMutation(
            str(selected),
            hook_entries_removed=hook_count,
            hook_entries_written=len(wanted),
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
    checkout_keys = set(codex_path_spellings(checkout))
    hooks_paths = codex_path_spellings(hooks_file_for(checkout))

    def plan(text: str, document: dict[str, Any]) -> tuple[str, TrustMutation]:
        hook_keys = {
            key for key in _all_hook_entries(document) if _hook_path(key) in hooks_paths
        }
        projects = checkout_keys & _project_entries(document).keys()
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
]
