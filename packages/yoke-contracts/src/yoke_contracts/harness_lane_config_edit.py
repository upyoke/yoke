"""Atomic format edits for harness state under Yoke-managed paths."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from yoke_contracts.codex_hook_trust_toml import (
    all_hook_entries,
    filter_tables,
    hook_path,
    mutate,
    read_config,
)


def backup(path: Path) -> str:
    """Keep exact pre-edit bytes beside the config, with private permissions."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = path.with_name(f"{path.name}.yoke-backup-{stamp}")
    with target.open("xb") as handle:
        os.chmod(target, 0o600)
        handle.write(path.read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    return str(target)


def _receipt(before: bytes, after: bytes, removed: int) -> dict:
    return dict(
        removed=removed, before_bytes=len(before), after_bytes=len(after), backup=""
    )


def codex_plan(text: str, document: dict, selected):
    projects = {key for key in document.get("projects", {}) if selected(key)}
    hooks = set()
    for key in all_hook_entries(document):
        raw = hook_path(key)
        if (
            raw
            and raw.endswith("/.codex/hooks.json")
            and selected(raw.removesuffix("/.codex/hooks.json"))
        ):
            hooks.add(key)
    updated, hook_count, project_count = filter_tables(text, hooks, projects)
    if hook_count != len(hooks) or project_count != len(projects):
        raise ValueError(
            "harness_lane_config_layout: expand inline TOML path tables and retry"
        )
    return updated, hook_count + project_count


def edit_codex(path: Path, selected, *, dry_run: bool, keep_backup: bool) -> dict:
    def plan(text, document):
        updated, removed = codex_plan(text, document, selected)
        receipt = _receipt(text.encode(), updated.encode(), removed)
        if updated != text and keep_backup and not dry_run:
            receipt["backup"] = backup(path)
        return (text if dry_run else updated), receipt

    if dry_run:
        return plan(*read_config(path))[1]
    return mutate(path, plan)


def edit_json(path: Path, selected, *, dry_run: bool, keep_backup: bool) -> dict:
    path = path.resolve()
    lock = path.with_name(f".{path.name}.yoke.lock")
    with nullcontext() if dry_run else FileLock(str(lock), timeout=10, mode=0o600):
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
        if not isinstance(document, dict) or not isinstance(
            document.get("projects", {}), dict
        ):
            raise ValueError(
                "harness_lane_config_malformed: expected a projects object"
            )
        projects = document.get("projects", {})
        owned = [key for key in projects if selected(key)]
        for key in owned:
            del projects[key]
        body = json.dumps(document, indent=2) + "\n" if owned else text
        receipt = _receipt(text.encode(), body.encode(), len(owned))
        if not owned or dry_run:
            return receipt
        if keep_backup:
            receipt["backup"] = backup(path)
        _replace(path, text, body)
        return receipt


def edit_cursor(path: Path, selected, *, dry_run: bool, keep_backup: bool) -> dict:
    before = path.read_bytes()
    document = json.loads(before)
    owner = document.get("workspacePath") if isinstance(document, dict) else None
    if not isinstance(owner, str):
        raise ValueError("harness_lane_config_malformed: expected workspacePath")
    owned = selected(owner)
    receipt = _receipt(before, b"" if owned else before, int(owned))
    if owned and not dry_run:
        if keep_backup:
            receipt["backup"] = backup(path)
        if path.read_bytes() != before:
            raise ValueError(
                "harness_lane_config_changed: retry after Cursor finishes writing"
            )
        path.unlink()
    return receipt


def _replace(path: Path, before: str, body: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.yoke-", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        if path.read_text(encoding="utf-8") != before:
            raise ValueError(
                "harness_lane_config_changed: retry after the harness finishes writing"
            )
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
