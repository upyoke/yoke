"""Undo the harness settings :mod:`harness_settings_ledger` says Yoke wrote.

A setting is reverted only while the harness still holds exactly the value
Yoke wrote; a value the operator has since changed is reported and left
alone, and one that is already gone needs nothing. Run twice, it is a no-op.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.hook_runner.config_owner import is_cursor_lifecycle_entry
from yoke_contracts.codex_config_posture import (
    CodexConfigUnreadable,
    parse_config,
    remove_top_level_key,
    remove_trust_table,
)
from yoke_contracts.harness_unattended_posture import (
    CODEX_PROJECTS_TABLE,
    CODEX_TRUST_LEVEL,
    CODEX_TRUST_LEVEL_KEY,
)

_MISSING = object()


def revert_recorded() -> Tuple[List[str], List[str]]:
    """Revert every recorded setting; return (report lines, failures)."""
    try:
        entries = ledger.read()
    except (OSError, ValueError) as exc:
        return [], [f"{ledger.ledger_path()} could not be read ({exc})"]
    lines: List[str] = []
    failures: List[str] = []
    for entry in entries:
        try:
            line = revert_entry(entry)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures.append(f"{entry.get('file')}: {type(exc).__name__}: {exc}")
        else:
            if line:
                lines.append(line)
    return lines, failures


def revert_entry(entry: Dict[str, Any]) -> str:
    """Revert one already-selected owned entry; report changes or preservation."""
    kind = entry["kind"]
    target = Path(entry["file"])
    if kind == "created_file":
        if not target.is_file():
            return ""
        target.unlink()
        return f"removed {target}"
    if not target.is_file():
        return ""
    if kind == "json":
        return _revert_json(
            target, list(entry["keys"]), entry["value"], int(entry["existing_depth"])
        )
    if kind == "codex_key":
        return _revert_codex_key(target, entry["key"], entry["value"])
    if kind == "codex_trust":
        return _revert_codex_trust(target, entry["trust_key"])
    raise ValueError(f"unknown recorded setting kind {kind!r}")


def _revert_json(target: Path, keys: List[str], value: Any, existing: int) -> str:
    payload = json.loads(target.read_text(encoding="utf-8"))
    dotted = ".".join(keys)
    parents: List[Dict[str, Any]] = []
    node: Any = payload
    for key in keys[:-1]:
        if not isinstance(node, dict) or not isinstance(node.get(key), dict):
            return ""
        parents.append(node)
        node = node[key]
    current = node.get(keys[-1], _MISSING) if isinstance(node, dict) else _MISSING
    if current is _MISSING:
        return ""
    if type(current) is not type(value) or current != value:
        return _left_alone(target, dotted, current)
    del node[keys[-1]]
    # Drop emptied containers Yoke created; keep every one that predated it.
    for depth in range(len(parents) - 1, existing - 1, -1):
        if parents[depth][keys[depth]]:
            break
        del parents[depth][keys[depth]]
    _replace(target, json.dumps(payload, indent=2) + "\n")
    return f"removed {dotted} from {target}"


def _revert_codex_key(target: Path, key: str, value: str) -> str:
    text = target.read_text(encoding="utf-8")
    current = _codex_config(text).get(key, _MISSING)
    if current is _MISSING:
        return ""
    if current != value:
        return _left_alone(target, key, current)
    updated = remove_top_level_key(text, key)
    if updated is None:
        return _left_alone(target, key, current)
    _replace(target, updated)
    return f"removed {key} from {target}"


def _revert_codex_trust(target: Path, trust_key: str) -> str:
    text = target.read_text(encoding="utf-8")
    table = (_codex_config(text).get(CODEX_PROJECTS_TABLE) or {}).get(trust_key)
    if not isinstance(table, dict) or CODEX_TRUST_LEVEL_KEY not in table:
        return ""
    dotted = f"{CODEX_PROJECTS_TABLE}[{trust_key}]"
    if table != {CODEX_TRUST_LEVEL_KEY: CODEX_TRUST_LEVEL}:
        return _left_alone(target, dotted, table)
    updated = remove_trust_table(text, trust_key)
    if updated is None:
        return _left_alone(target, dotted, table)
    _replace(target, updated)
    return f"removed {dotted} from {target}"


def remove_cursor_user_hooks(*, hooks_path: Optional[Path] = None) -> str:
    """Strip Yoke's entries from ``~/.cursor/hooks.json``; say what happened.

    Operator hooks stay. A file left holding nothing but empty hook lists is
    deleted, since Yoke created it. Unlike the installer this raises: uninstall
    must report a file it could not clean rather than claim it did.
    """
    path = hooks_path or (Path.home() / ".cursor" / "hooks.json")
    if not path.is_file():
        return f"no {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    hooks = payload.get("hooks") if isinstance(payload, dict) else None
    if not isinstance(hooks, dict):
        return f"no Yoke hooks in {path}"
    removed = 0
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        kept = [entry for entry in entries if not is_cursor_lifecycle_entry(entry)]
        removed += len(entries) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not removed:
        return f"no Yoke hooks in {path}"
    if not hooks and set(payload) <= {"hooks", "version"}:
        path.unlink()
        return f"deleted {path}"
    _replace(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return f"removed {removed} Yoke hook entries from {path}"


def _codex_config(text: str) -> Dict[str, Any]:
    try:
        return parse_config(text)
    except CodexConfigUnreadable as exc:
        raise ValueError(f"not valid TOML ({exc})") from exc


def _left_alone(target: Path, dotted: str, current: Any) -> str:
    return f"left your setting in place: {dotted} = {current!r} in {target}"


def _replace(target: Path, text: str) -> None:
    tmp = target.with_suffix(target.suffix + ".yoke-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


__all__ = ["remove_cursor_user_hooks", "revert_recorded", "revert_entry"]
