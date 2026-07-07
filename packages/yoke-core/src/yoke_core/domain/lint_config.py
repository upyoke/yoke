"""Project-local hook guard enforcement mode resolver.

The shared guard catalog and parser live in
``yoke_contracts.hook_runner.lint_policy`` so product clients and API servers
resolve the same ``.yoke/lint-config`` snapshot. This module owns only the
source-dev convenience of finding the checked-out config file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yoke_contracts.hook_runner import lint_policy

ALLOW_WARN_TOKEN = lint_policy.ALLOW_WARN_TOKEN
DENY = lint_policy.DENY
WARN = lint_policy.WARN
CONFIG_RELPATH = lint_policy.CONFIG_RELPATH
REMOTE_CLAUDE_CLI_GUARD = lint_policy.REMOTE_CLAUDE_CLI_GUARD
SNAPSHOT_PAYLOAD_KEY = lint_policy.SNAPSHOT_PAYLOAD_KEY
GUARD_CATALOG = lint_policy.GUARD_CATALOG
GuardSpec = lint_policy.GuardSpec

_PARSE_CACHE: Optional[dict[str, tuple[str, bool]]] = None
_ROOT_PARSE_CACHE: dict[str, dict[str, tuple[str, bool]]] = {}


def _workspace_root() -> Optional[str]:
    root = lint_policy.find_workspace_root()
    if root is not None:
        return str(root)
    try:
        from yoke_core.domain.worktree_paths import resolve_worktree_root

        return resolve_worktree_root()
    except RuntimeError:
        return None


def _normalize_root(root: Optional[str]) -> Optional[str]:
    if root is None:
        return None
    root = root.strip()
    if not root:
        return None
    try:
        return str(Path(root).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return os.path.abspath(os.path.expanduser(root))


def config_path(root: Optional[str] = None) -> Optional[str]:
    base = _normalize_root(root) if root is not None else _normalize_root(_workspace_root())
    return os.path.join(base, *CONFIG_RELPATH) if base else None


def _parse(path: Optional[str]) -> dict[str, tuple[str, bool]]:
    return lint_policy.parse_file(path)


def _cached_parse() -> dict[str, tuple[str, bool]]:
    global _PARSE_CACHE
    if _PARSE_CACHE is None:
        _PARSE_CACHE = _parse(config_path())
    return _PARSE_CACHE


def _cached_parse_for_root(root: str) -> dict[str, tuple[str, bool]]:
    normalized = _normalize_root(root)
    if normalized is None:
        return {}
    cached = _ROOT_PARSE_CACHE.get(normalized)
    if cached is None:
        cached = _parse(config_path(normalized))
        _ROOT_PARSE_CACHE[normalized] = cached
    return cached


def reset_cache() -> None:
    global _PARSE_CACHE
    _PARSE_CACHE = None
    _ROOT_PARSE_CACHE.clear()


def is_registered(guard_or_module: str) -> bool:
    return lint_policy.is_registered(guard_or_module)


def resolve_mode(guard_or_module: str, *, root: Optional[str] = None) -> str:
    parsed = _cached_parse_for_root(root) if root is not None else _cached_parse()
    return lint_policy.resolve_mode_from_entries(guard_or_module, parsed)


def snapshot(*, root: Optional[str] = None) -> dict[str, dict[str, object]]:
    parsed = _cached_parse_for_root(root) if root is not None else _cached_parse()
    return lint_policy.snapshot_from_entries(parsed)


def resolve_mode_from_snapshot(guard_or_module: str, value: object) -> str:
    return lint_policy.resolve_mode_from_snapshot(guard_or_module, value)


def resolve_mode_for_payload(
    guard_or_module: str,
    payload: object | None = None,
    *,
    root: Optional[str] = None,
) -> str:
    snapshot = (
        payload.get(SNAPSHOT_PAYLOAD_KEY)
        if isinstance(payload, dict) and SNAPSHOT_PAYLOAD_KEY in payload
        else None
    )
    if snapshot is not None:
        return resolve_mode_from_snapshot(guard_or_module, snapshot)
    return resolve_mode(guard_or_module, root=root)


def render_lint_config() -> str:
    return lint_policy.render_lint_config()


__all__ = [
    "ALLOW_WARN_TOKEN", "CONFIG_RELPATH", "DENY", "GUARD_CATALOG",
    "GuardSpec", "REMOTE_CLAUDE_CLI_GUARD", "SNAPSHOT_PAYLOAD_KEY", "WARN",
    "config_path", "is_registered", "render_lint_config", "reset_cache",
    "resolve_mode", "resolve_mode_for_payload", "resolve_mode_from_snapshot",
    "snapshot",
]
