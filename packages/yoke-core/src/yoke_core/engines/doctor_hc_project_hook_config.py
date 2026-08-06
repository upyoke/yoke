"""Validate Cursor-scanned hook configs in any checkout Yoke manages."""

from __future__ import annotations

import json
from pathlib import Path
import stat
from typing import Any

from yoke_cli.filesystem_safety import first_symlink_component
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.project_install.hook_entries import hook_entry_format
from yoke_cli.project_install.hook_schema import validate_hooks_subtree
from yoke_core.engines.doctor_context import resolve_context
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-project-hook-config-validity"
_HC_DESC = "Project Cursor-scanned hook configs are regular and schema-valid"
_CONFIG_PATHS = (
    Path(".claude/settings.json"),
    Path(".cursor/hooks.json"),
)
_CURSOR_CONFIG = Path(".cursor/hooks.json")
_UNREADABLE = object()


def _load_payload(root: Path, relative: Path, issues: list[str]) -> Any:
    path = root / relative
    symlink = first_symlink_component(root, path, include_leaf=True)
    if symlink is not None:
        issues.append(
            f"- {relative} crosses symlink component "
            f"{symlink.relative_to(root)}; Cursor refuses this config path"
        )
        return _UNREADABLE
    try:
        info = path.lstat()
    except OSError as exc:
        issues.append(f"- {relative} is unreadable: {exc}")
        return _UNREADABLE
    if not stat.S_ISREG(info.st_mode):
        issues.append(f"- {relative} is not a regular file")
        return _UNREADABLE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        issues.append(f"- {relative} is unreadable: {exc}")
    except json.JSONDecodeError as exc:
        issues.append(f"- {relative} is not valid JSON: {exc}")
    return _UNREADABLE


def _validate_payload(
    relative: Path,
    payload: Any,
    issues: list[str],
) -> None:
    if payload is _UNREADABLE:
        return
    if not isinstance(payload, dict):
        issues.append(f"- {relative} top level must be a JSON object")
        return
    if relative == _CURSOR_CONFIG:
        version = payload.get("version")
        if type(version) is not int or version != 1:
            issues.append(f"- {relative} must declare schema version 1")
    try:
        validate_hooks_subtree(
            payload.get("hooks"),
            label=f"{relative} hooks",
            entry_format=hook_entry_format(relative),
        )
    except ProjectInstallError as exc:
        issues.append(f"- {exc}")


def hc_project_hook_config_validity(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Check installed Claude/Cursor config shape without canonical comparison."""
    root = resolve_context(conn, args).source_checkout
    if root is None:
        rec.record(
            _HC_NAME,
            _HC_DESC,
            "FAIL",
            "selected project source checkout is unavailable",
        )
        return
    selected = Path(root)
    issues: list[str] = []
    for relative in _CONFIG_PATHS:
        _validate_payload(
            relative,
            _load_payload(selected, relative, issues),
            issues,
        )
    if issues:
        rec.record(_HC_NAME, _HC_DESC, "FAIL", "\n".join(issues))
        return
    rec.record(
        _HC_NAME,
        _HC_DESC,
        "PASS",
        "Claude and Cursor project hook configs are regular and schema-valid",
    )


__all__ = ["hc_project_hook_config_validity"]
