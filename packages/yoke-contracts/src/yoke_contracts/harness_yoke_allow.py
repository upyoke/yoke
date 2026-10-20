"""The one machine-wide allow entry that lets every harness run ``yoke``.

A harness decides whether to stop and ask before a command in two ways: a
permission mode, and an allowlist of commands that never ask. Setup seeds
the unattended mode only where the operator has not chosen one, so a
machine whose operator already set a mode or an allowlist keeps it — and,
before any project exists to install a project-level entry, every ``yoke``
call prompts. Running Yoke before a project exists is a core requirement,
so setup also adds exactly one entry per harness to its machine-wide
allowlist: the ``yoke`` command, nothing wider.

The entry is additive. Operator entries are never removed, reordered or
widened, the write is recorded in :mod:`harness_settings_ledger` so
``yoke uninstall`` removes exactly it, and :func:`yoke_posture` treats "mode
kept, ``yoke`` allowed" as healthy and "``yoke`` not allowed" as blocking.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.cursor_permissions import (
    CURSOR_CLI_REQUIRED_LIST,
    CURSOR_YOKE_ALLOW,
)
from yoke_contracts.harness_unattended_posture import (
    CLAUDE_FAMILY,
    CLAUDE_PERMISSIONS_CONTAINER,
    CODEX_FAMILY,
    CURSOR_FAMILY,
    POSTURE_ABSENT,
    POSTURE_PROMPTS,
    POSTURE_UNATTENDED,
    claude_config_path,
    claude_settings_path,
    claude_settings_problems,
    codex_config_path,
    cursor_config_path,
    managed_config_paths,
    posture_problems,
    read_posture_config,
)

#: The allow entry each harness reads, in that harness's own grammar.
YOKE_COMMAND_ALLOW: Dict[str, str] = {
    CLAUDE_FAMILY: "Bash(yoke:*)",
    CURSOR_FAMILY: CURSOR_YOKE_ALLOW,
    CODEX_FAMILY: 'prefix_rule(pattern = ["yoke"], decision = "allow")',
}

#: JSON harnesses keep the entry in ``permissions.allow``.
ALLOW_KEYS: Tuple[str, str] = (CLAUDE_PERMISSIONS_CONTAINER, "allow")

#: Codex reads every ``*.rules`` file in ``rules/`` beside its config.
CODEX_RULES_FILE = "yoke.rules"
CODEX_RULES_TEXT = (
    "# Written by `yoke setup` so the yoke command runs without asking.\n"
    "# `yoke uninstall` removes this file; deleting it undoes the change.\n"
    f"{YOKE_COMMAND_ALLOW[CODEX_FAMILY]}\n"
)


def yoke_allow_path(harness_id: str) -> Path:
    """The machine-wide file holding one harness's ``yoke`` allow entry."""
    if harness_id == CODEX_FAMILY:
        return codex_config_path().parent / "rules" / CODEX_RULES_FILE
    if harness_id == CURSOR_FAMILY:
        return cursor_config_path()
    return claude_settings_path()


def _load_json(target: Path) -> Dict[str, Any]:
    """The JSON object at *target*; ``{}`` when absent. Raises when malformed."""
    if not target.is_file():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} is not a JSON object")
    return payload


def yoke_allowed(harness_id: str) -> bool:
    """Whether the harness's machine-wide allowlist carries the entry."""
    target = yoke_allow_path(harness_id)
    try:
        if harness_id == CODEX_FAMILY:
            return target.is_file() and YOKE_COMMAND_ALLOW[CODEX_FAMILY] in (
                target.read_text(encoding="utf-8").splitlines()
            )
        container = _load_json(target).get(ALLOW_KEYS[0])
    except (OSError, ValueError):
        return False
    allow = container.get(ALLOW_KEYS[1]) if isinstance(container, dict) else None
    return isinstance(allow, list) and YOKE_COMMAND_ALLOW[harness_id] in allow


class YokePosture(NamedTuple):
    """Why ``yoke`` still prompts (``blocking``), and operator modes kept.

    Each entry names the file it was read from, so a reader never has to
    guess which of a harness's files holds the problem.
    """

    blocking: Tuple[str, ...]
    kept: Tuple[str, ...]


def yoke_posture(
    harness_id: str, surface_id: Optional[str] = None
) -> Optional[YokePosture]:
    """One harness's verdict, or ``None`` when it is not set up here.

    Claude's modes depend on the surface: ``claude-cli`` reads its settings
    file, ``claude-desktop`` its app preference, and an unnamed surface both
    (the preference only once the desktop has created its config). Both
    surfaces read the ``yoke`` allow entry from the same settings file.
    """
    if harness_id == CLAUDE_FAMILY:
        desktop_path, settings_path = claude_config_path(), claude_settings_path()
        if not (settings_path.parent.is_dir() or desktop_path.exists()):
            return None
        desktop, _reason = read_posture_config(harness_id, desktop_path)
        settings, reason = read_posture_config(harness_id, settings_path)
        if settings is None and settings_path.exists():
            return YokePosture((reason,), ())
        app = _sourced(desktop_path, posture_problems(harness_id, desktop or {}))
        cli = _sourced(settings_path, claude_settings_problems(settings or {}))
        mode = {"claude-cli": cli, "claude-desktop": app}.get(
            surface_id or "", (app if desktop else ()) + cli
        )
    else:
        config, _reason = read_posture_config(harness_id)
        if config is None:
            return None
        mode = _sourced(
            managed_config_paths()[harness_id], posture_problems(harness_id, config)
        )
    if not mode:
        return YokePosture((), ())
    if yoke_allowed(harness_id):
        return YokePosture((), mode)
    missing = (
        f"{YOKE_COMMAND_ALLOW[harness_id]} is not in {yoke_allow_path(harness_id)}"
    )
    return YokePosture((*mode, missing), ())


def _sourced(source: Path, problems: Tuple[str, ...]) -> Tuple[str, ...]:
    """Prefix each problem with the file it was read from."""
    return tuple(f"{source}: {problem}" for problem in problems)


def posture_state(harness_id: str) -> str:
    """Report whether ``yoke`` runs unprompted on one harness, as one word."""
    verdict = yoke_posture(harness_id)
    if verdict is None:
        return POSTURE_ABSENT
    return POSTURE_PROMPTS if verdict.blocking else POSTURE_UNATTENDED


def configure_yoke_allow(harness_id: str) -> List[str]:
    """Add the ``yoke`` entry to one harness's machine-wide allowlist.

    Returns the lines to report; empty when the harness is absent or the
    entry is already there.
    """
    target = yoke_allow_path(harness_id)
    home = codex_config_path().parent if harness_id == CODEX_FAMILY else target.parent
    if not home.is_dir() or yoke_allowed(harness_id):
        return []
    try:
        if harness_id == CODEX_FAMILY:
            recorded = _write_codex_rules(target)
        else:
            recorded = _merge_json_allow(harness_id, target)
    except (OSError, ValueError) as exc:
        return [
            f"{harness_id}: yoke_allow_failed: could not add "
            f"{YOKE_COMMAND_ALLOW[harness_id]} to {target} ({exc}); every yoke "
            "call will ask. Repair the file, then run "
            "`yoke doctor run --only harness-setup --fix`."
        ]
    unrecorded = [line for line in (ledger.record(e) for e in recorded) if line]
    return [
        f"{harness_id}: allowed yoke in {target} ({YOKE_COMMAND_ALLOW[harness_id]})",
        *(f"{harness_id}: {line}" for line in unrecorded),
    ]


def _write_codex_rules(target: Path) -> List[Dict[str, Any]]:
    if target.exists():
        raise ValueError(f"{target} already exists without the yoke rule")
    created_parent = not target.parent.is_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    _replace(target, CODEX_RULES_TEXT)
    return [ledger.created_file_entry(target)] + (
        [ledger.created_parent_dir_entry(target.parent)] if created_parent else []
    )


def _merge_json_allow(harness_id: str, target: Path) -> List[Dict[str, Any]]:
    """Append the entry to ``permissions.allow``; never touch other entries.

    Cursor's schema rejects a ``permissions`` object without ``deny``, which
    would drop the whole allowlist, so an absent ``deny`` is seeded empty.
    """
    payload = _load_json(target)
    container = payload.get(ALLOW_KEYS[0])
    if container is not None and not isinstance(container, dict):
        raise ValueError(f"{ALLOW_KEYS[0]} is not an object")
    allow = (container or {}).get(ALLOW_KEYS[1])
    if allow is not None and not isinstance(allow, list):
        raise ValueError(f"{'.'.join(ALLOW_KEYS)} is not a list")
    entry = YOKE_COMMAND_ALLOW[harness_id]
    recorded = [
        ledger.json_list_item_entry(
            target, list(ALLOW_KEYS), entry, existing_depth=_depth(payload)
        )
    ]
    deny_keys = [ALLOW_KEYS[0], CURSOR_CLI_REQUIRED_LIST]
    if harness_id == CURSOR_FAMILY and CURSOR_CLI_REQUIRED_LIST not in (
        container or {}
    ):
        recorded.append(
            ledger.json_entry(
                target,
                deny_keys,
                [],
                existing_depth=ledger.existing_depth(payload, deny_keys[:-1]),
            )
        )
    container = payload.setdefault(ALLOW_KEYS[0], {})
    container.setdefault(ALLOW_KEYS[1], []).append(entry)
    if harness_id == CURSOR_FAMILY:
        container.setdefault(CURSOR_CLI_REQUIRED_LIST, [])
    _replace(target, json.dumps(payload, indent=2) + "\n")
    return recorded


def _depth(payload: Dict[str, Any]) -> int:
    """Containers on ``permissions.allow`` that predate the write, list included."""
    depth = ledger.existing_depth(payload, [ALLOW_KEYS[0]])
    if depth and isinstance(payload[ALLOW_KEYS[0]].get(ALLOW_KEYS[1]), list):
        depth += 1
    return depth


def _replace(target: Path, text: str) -> None:
    tmp = target.with_suffix(target.suffix + ".yoke-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


__all__ = [
    "ALLOW_KEYS",
    "CODEX_RULES_FILE",
    "CODEX_RULES_TEXT",
    "YOKE_COMMAND_ALLOW",
    "YokePosture",
    "configure_yoke_allow",
    "posture_state",
    "yoke_allow_path",
    "yoke_allowed",
    "yoke_posture",
]
