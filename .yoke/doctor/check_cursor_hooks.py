"""HCs covering the Cursor hook substrate.

Three checks share this module because they read the Cursor hook artefacts
(``runtime/harness/cursor/hooks.json`` and its repo-root surfacing):

* ``HC-cursor-hook-events`` — required Cursor event entries are present in
  ``runtime/harness/cursor/hooks.json`` with the schema version marker.
* ``HC-cursor-hook-surfacing`` — the repo-root ``.cursor/agents`` symlink and
  materialized ``.cursor/hooks.json`` are present.
* ``HC-cursor-hook-config-drift`` — the materialized hook file is byte-identical
  to the canonical runtime file.

Byte-level render drift is ``HC-harness-substrate-drift``'s job; these
checks assert the wired shape Cursor actually loads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


# Required Cursor-native events in hooks.json. The shell gate rides
# beforeShellExecution; preToolUse carries the Write|Read|Task matcher; the
# IDE-only events (beforeSubmitPrompt, stop) still render so the IDE surface
# gets them, even though the non-interactive terminal agent never fires them.
# afterAgentThought is the only event that names a concrete model, so losing
# it leaves terminal-agent sessions recorded with an unknown model.
_REQUIRED_EVENTS: tuple[str, ...] = (
    "sessionStart",
    "sessionEnd",
    "beforeSubmitPrompt",
    "beforeShellExecution",
    "afterShellExecution",
    "preToolUse",
    "postToolUse",
    "postToolUseFailure",
    "stop",
    "afterAgentThought",
)

_HOOKS_PATH = Path("runtime/harness/cursor/hooks.json")
_NATIVE_HOOKS_PATH = Path(".cursor/hooks.json")
_NATIVE_AGENT_LINKS: tuple[tuple[str, str], ...] = (
    (".cursor/agents", "../runtime/harness/cursor/agents"),
)


def _root() -> Path:
    root = _resolve_repo_root()
    return Path(root) if root else Path(".")


def hc_cursor_hook_events(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    name = "cursor-hook-events"
    desc = "Cursor hooks.json carries the required events and schema version"
    p = _root() / _HOOKS_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        rec.record(name, desc, "FAIL", f"unreadable {_HOOKS_PATH}: {exc}")
        return
    if data.get("version") != 1:
        rec.record(
            name, desc, "FAIL",
            f"{_HOOKS_PATH} must declare schema version 1 — Cursor refuses "
            "schema-invalid hook files outright",
        )
        return
    hooks = data.get("hooks") or {}
    missing: List[str] = [
        event for event in _REQUIRED_EVENTS
        if not isinstance(hooks.get(event), list) or not hooks.get(event)
    ]
    if missing:
        rec.record(
            name, desc, "FAIL",
            "missing required hook events: " + ", ".join(missing),
        )
        return
    rec.record(
        name, desc, "PASS",
        f"all {len(_REQUIRED_EVENTS)} required events present (version 1)",
    )


def hc_cursor_hook_surfacing(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    name = "cursor-hook-surfacing"
    desc = "Repo-root Cursor surfaces reach the rendered Cursor substrate"
    root = _root()
    problems: List[str] = []
    hooks_file = root / _NATIVE_HOOKS_PATH
    if hooks_file.is_symlink():
        problems.append(
            f"{_NATIVE_HOOKS_PATH} is a symlink; Cursor refuses project "
            "hook config paths containing symlinks"
        )
    elif not hooks_file.is_file():
        problems.append(f"{_NATIVE_HOOKS_PATH} is not a regular file")
    for rel, expected_target in _NATIVE_AGENT_LINKS:
        link = root / rel
        if not link.is_symlink():
            problems.append(f"{rel} is not a symlink")
            continue
        try:
            actual = str(link.readlink())
        except OSError as exc:
            problems.append(f"{rel} unreadable: {exc}")
            continue
        if actual != expected_target:
            problems.append(f"{rel} -> {actual} (expected {expected_target})")
    if problems:
        rec.record(name, desc, "FAIL", "; ".join(problems))
        return
    rec.record(
        name,
        desc,
        "PASS",
        "materialized .cursor/hooks.json and .cursor/agents surface the "
        "rendered tree",
    )


def cursor_hook_config_diagnostics(root: Path) -> List[str]:
    """Return static Cursor config problems that can produce zero loaded hooks."""
    native = root / _NATIVE_HOOKS_PATH
    canonical = root / _HOOKS_PATH
    if native.is_symlink():
        return [
            f"{_NATIVE_HOOKS_PATH} is a symlink; Cursor may report zero loaded "
            "hooks for this project"
        ]
    if not native.is_file():
        return [f"{_NATIVE_HOOKS_PATH} is missing or not a regular file"]
    if not canonical.is_file():
        return [f"canonical {_HOOKS_PATH} is missing or not a regular file"]
    try:
        native_bytes = native.read_bytes()
        canonical_bytes = canonical.read_bytes()
    except OSError as exc:
        return [f"Cursor hook config drift check could not read files: {exc}"]
    if native_bytes != canonical_bytes:
        return [
            f"{_NATIVE_HOOKS_PATH} differs from canonical {_HOOKS_PATH}; "
            "Cursor may report zero loaded hooks"
        ]
    return []


def hc_cursor_hook_config_drift(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "cursor-hook-config-drift"
    desc = "Materialized Cursor hook config matches the canonical runtime file"
    problems = cursor_hook_config_diagnostics(_root())
    if problems:
        rec.record(name, desc, "FAIL", "; ".join(problems))
        return
    rec.record(name, desc, "PASS", "Cursor hook config is byte-identical to canonical")


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ("cursor-hook-events", "Cursor hooks.json carries required events + schema version", hc_cursor_hook_events),
    ("cursor-hook-surfacing", "Repo-root Cursor surfaces reach rendered Cursor substrate", hc_cursor_hook_surfacing),
    ("cursor-hook-config-drift", "Materialized Cursor hook config matches canonical runtime file", hc_cursor_hook_config_drift),
)
