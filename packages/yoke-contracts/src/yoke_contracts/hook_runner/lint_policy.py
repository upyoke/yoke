"""Shared hook guard policy contract.

The project-local ``.yoke/lint-config`` file is client authority: hook
evaluation may be split between a local product client and an HTTPS server, but
the operator's checked-out policy must travel with the hook payload and be
resolved identically on both sides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional, Tuple

from yoke_contracts.hook_runner.hook_guard_catalog import (
    DB_COMMAND_STABLE_CHECK_ID,
    GUARD_CATALOG,
    REMOTE_CLAUDE_CLI_GUARD,
    GuardSpec,
)

DENY = "deny"
WARN = "warn"
VALID_MODES = (DENY, WARN)
ALLOW_WARN_TOKEN = "# allow-warn"
CONFIG_RELPATH = (".yoke", "lint-config")
# Consulted in order by ``find_workspace_root`` before falling back to
# walking up from the starting directory. Reporting surfaces read this
# rather than restating the order.
WORKSPACE_ROOT_ENV_VARS: Tuple[str, ...] = (
    "YOKE_TARGET_REPO_ROOT",
    "CLAUDE_PROJECT_DIR",
    "CODEX_PROJECT_DIR",
    "YOKE_REPO_ROOT",
)
SNAPSHOT_PAYLOAD_KEY = "_yoke_lint_config"

_BY_GUARD: dict[str, GuardSpec] = {}
_BY_MODULE: dict[str, GuardSpec] = {}
for _spec in GUARD_CATALOG:
    _BY_GUARD[_spec.guard] = _spec
    for _alias in _spec.aliases:
        _BY_GUARD[_alias] = _spec
    _BY_MODULE[_spec.module] = _spec
    for _alias in _spec.module_aliases:
        _BY_MODULE[_alias] = _spec


def short_id(guard_or_module: str) -> str:
    return (
        guard_or_module.rsplit(".", 1)[-1]
        if "." in guard_or_module
        else guard_or_module
    )


def spec_for(guard_or_module: str) -> GuardSpec | None:
    return _BY_MODULE.get(guard_or_module) or _BY_GUARD.get(short_id(guard_or_module))


def is_registered(guard_or_module: str) -> bool:
    return spec_for(guard_or_module) is not None


def parse_text(text: str) -> dict[str, tuple[str, bool]]:
    """Parse lint-config text into ``guard -> (mode, allow_warn_token)``."""
    parsed: dict[str, tuple[str, bool]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key:
            continue
        allow_warn = ALLOW_WARN_TOKEN in rest
        value = rest.split("#", 1)[0].strip().lower()
        if value in VALID_MODES:
            parsed[key] = (value, allow_warn)
    return parsed


def parse_file(path: str | os.PathLike[str] | None) -> dict[str, tuple[str, bool]]:
    if not path:
        return {}
    selected = Path(path)
    if not selected.is_file():
        return {}
    try:
        return parse_text(selected.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}


def resolve_mode_from_entries(
    guard_or_module: str,
    entries: Mapping[str, tuple[str, bool]],
) -> str:
    spec = spec_for(guard_or_module)
    if spec is None:
        return DENY
    entry = entries.get(spec.guard)
    if entry is None:
        for alias in spec.aliases:
            entry = entries.get(alias)
            if entry is not None:
                break
    if entry is None:
        return DENY
    mode, allow_warn = entry
    if mode == WARN and spec.protected and not allow_warn:
        return DENY
    return mode


def snapshot_from_entries(
    entries: Mapping[str, tuple[str, bool]],
) -> dict[str, dict[str, object]]:
    return {
        guard: {"mode": mode, "allow_warn": bool(allow_warn)}
        for guard, (mode, allow_warn) in entries.items()
        if mode in VALID_MODES
    }


def entries_from_snapshot(value: object) -> dict[str, tuple[str, bool]]:
    if not isinstance(value, Mapping):
        return {}
    entries: dict[str, tuple[str, bool]] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        if isinstance(raw, Mapping):
            mode = str(raw.get("mode") or "").lower()
            allow_warn = bool(raw.get("allow_warn"))
        else:
            mode = str(raw).lower()
            allow_warn = False
        if mode in VALID_MODES:
            entries[key] = (mode, allow_warn)
    return entries


def snapshot_from_file(
    path: str | os.PathLike[str] | None,
) -> dict[str, dict[str, object]]:
    return snapshot_from_entries(parse_file(path))


def resolve_mode_from_snapshot(guard_or_module: str, snapshot: object) -> str:
    return resolve_mode_from_entries(guard_or_module, entries_from_snapshot(snapshot))


def find_workspace_root(start: str | os.PathLike[str] | None = None) -> Optional[Path]:
    for key in WORKSPACE_ROOT_ENV_VARS:
        value = os.environ.get(key)
        if value:
            return Path(value).expanduser().resolve(strict=False)
    current = Path(start or os.getcwd()).expanduser().resolve(strict=False)
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_RELPATH[0] / CONFIG_RELPATH[1]).is_file():
            return candidate
    return None


def config_path_for_root(root: str | os.PathLike[str] | None = None) -> Optional[Path]:
    base = (
        Path(root).expanduser().resolve(strict=False) if root else find_workspace_root()
    )
    return base / CONFIG_RELPATH[0] / CONFIG_RELPATH[1] if base else None


def snapshot_from_workspace(
    *,
    root: str | os.PathLike[str] | None = None,
    start: str | os.PathLike[str] | None = None,
) -> dict[str, dict[str, object]]:
    base = config_path_for_root(root) if root else None
    if base is None and root is None:
        found = find_workspace_root(start)
        base = found / CONFIG_RELPATH[0] / CONFIG_RELPATH[1] if found else None
    path = base
    return snapshot_from_file(path)


def render_lint_config() -> str:
    lines = [
        "# Yoke hook-guard enforcement modes - project-local policy.",
        "# One line per guard: <guard>=deny|warn  (deny blocks; warn observes only).",
        "# Protected guards (security/integrity) refuse warn unless the line ends",
        f"# with the `{ALLOW_WARN_TOKEN}` override token.",
        "",
    ]
    for spec in GUARD_CATALOG:
        protection = (
            "  [protected: warn needs `# allow-warn`]" if spec.protected else ""
        )
        lines.append(f"# {spec.description}{protection}")
        if spec.aliases:
            aliases = ", ".join(spec.aliases)
            lines.append(f"# Legacy stable config aliases still accepted: {aliases}")
        if spec.compatibility_id:
            lines.append(
                f"# Stable telemetry compatibility id: {spec.compatibility_id}"
            )
        lines.append(f"{spec.guard}={DENY}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "ALLOW_WARN_TOKEN",
    "CONFIG_RELPATH",
    "DB_COMMAND_STABLE_CHECK_ID",
    "DENY",
    "GUARD_CATALOG",
    "GuardSpec",
    "REMOTE_CLAUDE_CLI_GUARD",
    "SNAPSHOT_PAYLOAD_KEY",
    "WARN",
    "config_path_for_root",
    "entries_from_snapshot",
    "find_workspace_root",
    "is_registered",
    "parse_file",
    "parse_text",
    "render_lint_config",
    "resolve_mode_from_entries",
    "resolve_mode_from_snapshot",
    "short_id",
    "snapshot_from_entries",
    "snapshot_from_file",
    "snapshot_from_workspace",
    "spec_for",
]
