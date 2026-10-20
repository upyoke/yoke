"""Undo the harness settings :mod:`harness_settings_ledger` says Yoke wrote.

A setting is reverted only while the harness still holds exactly the value
Yoke wrote; a value the operator has since changed is reported and left
alone, and one that is already gone needs nothing. Run twice, it is a no-op.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.codex_config_posture import (
    remove_top_level_key,
    remove_trust_table,
)
from yoke_contracts.codex_hook_trust_toml import CodexHookTrustStoreError, mutate
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
    if kind == "created_dir":
        return _revert_created_dir(target)
    if kind == "created_parent_dir":
        return _revert_parent_dir(target)
    if not target.is_file():
        return ""
    if kind == "json":
        return _revert_json(
            target, list(entry["keys"]), entry["value"], int(entry["existing_depth"])
        )
    if kind == "json_list_item":
        return _revert_json_list_item(
            target, list(entry["keys"]), entry["value"], int(entry["existing_depth"])
        )
    if kind == "codex_key":
        return _revert_codex_key(target, entry["key"], entry["value"])
    if kind == "codex_trust":
        return _revert_codex_trust(target, entry["trust_key"])
    raise ValueError(f"unknown recorded setting kind {kind!r}")


def _revert_created_dir(target: Path) -> str:
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    else:
        return ""
    return f"removed {target}"


def _revert_parent_dir(target: Path) -> str:
    """Remove a folder Yoke made to hold its entries, but only once empty."""
    if target.is_symlink() or not target.is_dir():
        return ""
    if any(target.iterdir()):
        return f"kept {target}: it holds files Yoke did not put there"
    target.rmdir()
    return f"removed empty {target}"


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


def _revert_json_list_item(
    target: Path, keys: List[str], value: Any, existing: int
) -> str:
    """Remove the one appended value; drop the containers Yoke created."""
    payload = json.loads(target.read_text(encoding="utf-8"))
    path: List[Any] = [payload]
    for key in keys:
        node = path[-1]
        child = node.get(key) if isinstance(node, dict) else None
        if not isinstance(child, (dict, list)):
            return ""
        path.append(child)
    items = path[-1]
    if not isinstance(items, list) or value not in items:
        return ""
    items.remove(value)
    # path[d + 1] is the container at keys[d]; keep every one that predated.
    for depth in range(len(keys) - 1, existing - 1, -1):
        if path[depth + 1]:
            break
        del path[depth][keys[depth]]
    _replace(target, json.dumps(payload, indent=2) + "\n")
    return f"removed {value!r} from {'.'.join(keys)} in {target}"


def _revert_codex_key(target: Path, key: str, value: str) -> str:
    def plan(text, document):
        current = document.get(key, _MISSING)
        if current is _MISSING:
            return text, ""
        if current != value:
            return text, _left_alone(target, key, current)
        updated = remove_top_level_key(text, key)
        if updated is None:
            return text, _left_alone(target, key, current)
        return updated, f"removed {key} from {target}"

    return _mutate_codex(target, plan)


def _revert_codex_trust(target: Path, trust_key: str) -> str:
    def plan(text, document):
        table = (document.get(CODEX_PROJECTS_TABLE) or {}).get(trust_key)
        if not isinstance(table, dict) or CODEX_TRUST_LEVEL_KEY not in table:
            return text, ""
        dotted = f"{CODEX_PROJECTS_TABLE}[{trust_key}]"
        if table != {CODEX_TRUST_LEVEL_KEY: CODEX_TRUST_LEVEL}:
            return text, _left_alone(target, dotted, table)
        updated = remove_trust_table(text, trust_key)
        if updated is None:
            return text, _left_alone(target, dotted, table)
        return updated, f"removed {dotted} from {target}"

    return _mutate_codex(target, plan)


def _mutate_codex(target, planner):
    try:
        return mutate(target, planner)
    except CodexHookTrustStoreError as exc:
        raise ValueError(str(exc)) from exc


def _left_alone(target: Path, dotted: str, current: Any) -> str:
    return f"left your setting in place: {dotted} = {current!r} in {target}"


def _replace(target: Path, text: str) -> None:
    tmp = target.with_suffix(target.suffix + ".yoke-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


__all__ = ["revert_recorded", "revert_entry"]
