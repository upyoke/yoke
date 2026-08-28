"""HCs covering the Cursor hook substrate.

Three checks share this module because they read the Cursor hook artefacts
(``runtime/harness/cursor/hooks.json`` plus every project config Cursor scans):

* ``HC-cursor-hook-events`` — required Cursor event entries are present in
  ``runtime/harness/cursor/hooks.json`` with the schema version marker.
* ``HC-cursor-hook-surfacing`` — the repo-root ``.cursor/agents`` symlink and
  materialized Cursor/Claude project configs are present.
* ``HC-cursor-hook-config-drift`` — both materialized config files are
  byte-identical to their canonical runtime files.

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
from yoke_cli.filesystem_safety import first_symlink_component


# Required Cursor-native events in hooks.json. The shell gate rides
# beforeShellExecution; preToolUse matches every tool except Shell; the
# IDE-only events (beforeSubmitPrompt, stop) still render so the IDE surface
# gets them, even though the non-interactive terminal agent never fires them.
# afterAgentThought is required to be ABSENT rather than present: it fires
# inside the token stream, and a hook there breaks the stream whatever it
# replies. See _FORBIDDEN_EVENTS below.
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
)

# Cursor-native events that must carry no hook entry at all. The generation
# stream is held open across a hook on afterAgentThought, and on cursor-agent
# 2026.08.25 even `exit 0` breaks it once per thought until the reconnects run
# out and the run dies as `RetriableError: WritableIterable is closed`.
_FORBIDDEN_EVENTS: tuple[str, ...] = ("afterAgentThought",)

_HOOKS_PATH = Path("runtime/harness/cursor/hooks.json")
_NATIVE_HOOKS_PATH = Path(".cursor/hooks.json")
_CLAUDE_HOOKS_PATH = Path("runtime/harness/claude/settings.json")
_CLAUDE_PROJECT_HOOKS_PATH = Path(".claude/settings.json")
_MATERIALIZED_CONFIGS = (
    (_NATIVE_HOOKS_PATH, _HOOKS_PATH),
    (_CLAUDE_PROJECT_HOOKS_PATH, _CLAUDE_HOOKS_PATH),
)
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
            name,
            desc,
            "FAIL",
            f"{_HOOKS_PATH} must declare schema version 1 — Cursor refuses "
            "schema-invalid hook files outright",
        )
        return
    hooks = data.get("hooks") or {}
    missing: List[str] = [
        event
        for event in _REQUIRED_EVENTS
        if not isinstance(hooks.get(event), list) or not hooks.get(event)
    ]
    if missing:
        rec.record(
            name,
            desc,
            "FAIL",
            "missing required hook events: " + ", ".join(missing),
        )
        return
    wired_in_stream = [event for event in _FORBIDDEN_EVENTS if hooks.get(event)]
    if wired_in_stream:
        rec.record(
            name,
            desc,
            "FAIL",
            "hook wired inside the generation stream: "
            + ", ".join(wired_in_stream)
            + " — Cursor holds the stream open across the hook and the run "
            "dies as RetriableError: WritableIterable is closed. Remove the "
            f"entry from {_HOOKS_PATH} and re-render.",
        )
        return
    rec.record(
        name,
        desc,
        "PASS",
        f"all {len(_REQUIRED_EVENTS)} required events present (version 1), "
        f"{len(_FORBIDDEN_EVENTS)} in-stream event unwired",
    )


def hc_cursor_hook_surfacing(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    name = "cursor-hook-surfacing"
    desc = "Repo-root Cursor surfaces reach the rendered Cursor substrate"
    root = _root()
    problems: List[str] = []
    for project_path, _canonical_path in _MATERIALIZED_CONFIGS:
        hooks_file = root / project_path
        symlink = first_symlink_component(
            root,
            hooks_file,
            include_leaf=True,
        )
        if symlink is not None:
            problems.append(
                f"{project_path} contains symlink component "
                f"{symlink.relative_to(root)}; "
                "Cursor refuses project hook config paths containing symlinks"
            )
        elif not hooks_file.is_file():
            problems.append(f"{project_path} is not a regular file")
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
        "materialized Cursor/Claude hook configs and .cursor/agents surface "
        "the rendered tree",
    )


def cursor_hook_config_diagnostics(root: Path) -> List[str]:
    """Return static Cursor config problems that can produce zero loaded hooks."""
    problems: List[str] = []
    for project_path, canonical_path in _MATERIALIZED_CONFIGS:
        native = root / project_path
        canonical = root / canonical_path
        symlink = first_symlink_component(
            root,
            native,
            include_leaf=True,
        )
        if symlink is not None:
            problems.append(
                f"{project_path} contains symlink component "
                f"{symlink.relative_to(root)}; "
                "Cursor may reject this project config"
            )
            continue
        if not native.is_file():
            problems.append(f"{project_path} is missing or not a regular file")
            continue
        if not canonical.is_file():
            problems.append(
                f"canonical {canonical_path} is missing or not a regular file"
            )
            continue
        try:
            if native.read_bytes() != canonical.read_bytes():
                problems.append(
                    f"{project_path} differs from canonical {canonical_path}"
                )
        except OSError as exc:
            problems.append(
                f"Cursor hook config drift check could not read files: {exc}"
            )
    return problems


def hc_cursor_hook_config_drift(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    name = "cursor-hook-config-drift"
    desc = "Cursor-scanned hook configs match their canonical runtime files"
    problems = cursor_hook_config_diagnostics(_root())
    if problems:
        rec.record(name, desc, "FAIL", "; ".join(problems))
        return
    rec.record(
        name, desc, "PASS", "Cursor-scanned configs are byte-identical to canonical"
    )


from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        "cursor-hook-events",
        "Cursor hooks.json carries required events + schema version",
        hc_cursor_hook_events,
    ),
    (
        "cursor-hook-surfacing",
        "Repo-root Cursor surfaces reach rendered Cursor substrate",
        hc_cursor_hook_surfacing,
    ),
    (
        "cursor-hook-config-drift",
        "Cursor-scanned hook configs match canonical runtime files",
        hc_cursor_hook_config_drift,
    ),
)
