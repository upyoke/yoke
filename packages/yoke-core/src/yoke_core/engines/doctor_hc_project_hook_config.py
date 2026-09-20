"""Validate every harness hook config in any checkout Yoke manages.

A flat ``{type, command}`` entry where the nested ``{hooks: [...]}`` form
belongs costs a harness every hook in the file, silently, so the shape is
checked per config rather than trusted because Yoke rendered it.
"""

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
_HC_DESC = "Project hook configs are regular and schema-valid"
_CONFIG_PATHS = (
    Path(".claude/settings.json"),
    Path(".codex/hooks.json"),
    Path(".cursor/hooks.json"),
)
_CURSOR_CONFIG = Path(".cursor/hooks.json")

#: Cursor refuses a hook config reached through a symlink, and it scans both
#: its own file and Claude's, so for these two a symlink is a real defect that
#: silently costs the project its hooks. Codex reads its own file directly and
#: accepts a link, which is how Yoke's own checkout ships it — `.codex/hooks.json`
#: points into `runtime/harness/codex/`. Applying Cursor's constraint to the
#: Codex path would fail every checkout that follows Yoke's own layout, so the
#: rejection stays scoped to the scanners that have it.
_CURSOR_SCANNED_CONFIGS = frozenset({Path(".claude/settings.json"), _CURSOR_CONFIG})

#: Configs whose absence is a harness this project does not wire rather than a
#: defect. Yoke writes `.codex/hooks.json` only where Codex is in use, so a
#: checkout without one has no shape to be wrong; the other two keep the
#: presence expectations they already had, because relaxing those would drop a
#: protection this check did not set out to change.
_OPTIONAL_CONFIGS = frozenset({Path(".codex/hooks.json")})
_UNREADABLE = object()


def _load_payload(root: Path, relative: Path, issues: list[str]) -> Any:
    path = root / relative
    if relative in _CURSOR_SCANNED_CONFIGS:
        symlink = first_symlink_component(root, path, include_leaf=True)
        if symlink is not None:
            issues.append(
                f"- {relative} crosses symlink component "
                f"{symlink.relative_to(root)}; Cursor refuses this config path"
            )
            return _UNREADABLE
    # Resolve through a link rather than describing it: the Cursor-scanned
    # configs already proved they cross no symlink, so this agrees with their
    # own lstat, and the Codex path is expected to be a link to a regular file.
    try:
        info = path.stat()
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
    """Check installed hook-config shape without canonical comparison."""
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
    checked: list[str] = []
    for relative in _CONFIG_PATHS:
        if relative in _OPTIONAL_CONFIGS and not (selected / relative).exists():
            continue
        checked.append(str(relative))
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
        # Name the files rather than the harnesses: an optional config this
        # checkout does not carry is absent from the list, so a reader can see
        # what was examined instead of inferring it from a PASS.
        "regular and schema-valid: " + ", ".join(checked),
    )


__all__ = ["hc_project_hook_config_validity"]
