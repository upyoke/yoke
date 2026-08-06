"""Migrate former board.json + machine board.scope into project-policy.

Uses the registered ``projects.capability_settings.*`` surface so the
same helper works against https control planes (no local DB connect).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.board.policy_settings import merge_board_file_values
from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema_projects import normalize_project_id
from yoke_contracts.project_contract.board_art.config_paths import board_config_path


def _read_board_json(checkout: Path) -> dict[str, Any]:
    path = board_config_path(checkout)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _machine_board_scope(entry: Mapping[str, Any]) -> str | None:
    board = entry.get("board")
    if not isinstance(board, Mapping):
        return None
    raw = board.get("scope")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _yoke_json(*args: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["yoke", *args, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"yoke {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr or proc.stdout}"
        )
    # Skip advisory lines before the JSON envelope.
    text = proc.stdout
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"no JSON from yoke {' '.join(args)}: {text!r}")
    envelope = json.loads(text[start:])
    if not envelope.get("success", True):
        raise RuntimeError(f"yoke {' '.join(args)} error: {envelope}")
    return dict(envelope.get("result") or {})


def _project_slug(project_id: int) -> str:
    rows = _yoke_json(
        "db", "read",
        f"SELECT slug FROM projects WHERE id = {int(project_id)}",
    )
    for row in rows.get("rows") or []:
        if row:
            return str(row[0])
    raise LookupError(f"project id {project_id} not found")


def _write_board_settings(project: str, board: Mapping[str, Any]) -> None:
    sets: list[str] = []
    for key, value in board.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = str(value)
        sets.extend(["--set", f"board.{key}={rendered}"])
    if not sets:
        return
    _yoke_json(
        "projects", "capability-settings", "merge",
        "--project", project,
        "--cap-type", "project-policy",
        *sets,
    )


def migrate_mapped_checkouts(*, delete_files: bool = False) -> list[dict[str, Any]]:
    """Migrate every machine-config project entry; optionally delete board.json."""

    cfg = machine_config.load_config()
    projects = cfg.get("projects") or []
    if not isinstance(projects, list):
        return []
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    for entry in projects:
        if not isinstance(entry, Mapping):
            continue
        checkout_raw = entry.get("checkout")
        pid = normalize_project_id(entry.get("project_id"))
        if not checkout_raw or pid is None or int(pid) in seen:
            continue
        seen.add(int(pid))
        checkout = Path(str(checkout_raw)).expanduser()
        file_values = _read_board_json(checkout)
        scope = _machine_board_scope(entry)
        merged = merge_board_file_values(None, file_values, scope=scope)
        slug = _project_slug(int(pid))
        _write_board_settings(slug, merged)
        deleted = False
        board_path = board_config_path(checkout)
        if delete_files and board_path.is_file():
            board_path.unlink()
            deleted = True
        results.append({
            "checkout": str(checkout),
            "project_id": int(pid),
            "project": slug,
            "scope": merged.get("scope"),
            "deleted_board_json": deleted,
        })
    return results


def strip_machine_board_entries() -> int:
    """Remove ``projects[].board`` from the active machine config."""

    from yoke_cli.config.machine_config_mutation import (
        load_payload,
        write_payload,
    )

    payload, cfg_path = load_payload(None)
    projects = payload.get("projects")
    if not isinstance(projects, list):
        return 0
    removed = 0
    for entry in projects:
        if isinstance(entry, dict) and "board" in entry:
            entry.pop("board", None)
            removed += 1
    if removed:
        write_payload(payload, cfg_path)
    return removed


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.board_settings_migrate",
    )
    parser.add_argument("--delete-files", action="store_true")
    parser.add_argument("--strip-machine-board", action="store_true")
    args = parser.parse_args()
    results = migrate_mapped_checkouts(delete_files=args.delete_files)
    for row in results:
        print(
            f"migrated project={row['project']} id={row['project_id']} "
            f"scope={row['scope']} checkout={row['checkout']} "
            f"deleted={row['deleted_board_json']}"
        )
    if args.strip_machine_board:
        print(f"stripped_machine_board_entries={strip_machine_board_entries()}")
    print(f"migrated_count={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
