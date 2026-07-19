"""Three-way Pack merge planning with project customizations as local edits."""

from __future__ import annotations

import hashlib
import base64
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any, Mapping


class PackMergeError(RuntimeError):
    """A Pack update cannot be planned safely."""


def plan_get(
    repo_root: Path,
    desired: list[dict[str, Any]],
) -> dict[str, Any]:
    creates: list[dict[str, Any]] = []
    unchanged: list[str] = []
    conflicts: list[dict[str, Any]] = []
    for wanted in desired:
        current = file_state(repo_root / wanted["path"])
        if current is None:
            creates.append(_write(wanted["path"], wanted))
        elif _matches(current, wanted):
            unchanged.append(wanted["path"])
        else:
            conflicts.append({"path": wanted["path"], "reason": "existing_project_file"})
    return _plan(creates, [], unchanged, conflicts, [])


def plan_update(
    repo_root: Path,
    old_entries: list[dict[str, Any]],
    new_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    old = {row["path"]: row for row in old_entries}
    new = {row["path"]: row for row in new_entries}
    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    unchanged: list[str] = []
    conflicts: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []

    for path in sorted(new):
        wanted = new[path]
        prior = old.get(path)
        current = file_state(repo_root / path)
        if prior is None:
            if current is None:
                creates.append(_write(path, wanted))
            elif _matches(current, wanted):
                unchanged.append(path)
            else:
                conflicts.append({"path": path, "reason": "new_pack_file_collides"})
            continue
        if current is None:
            if _matches(prior, wanted):
                retained.append(
                    {"path": path, "reason": "project_removed_unchanged_upstream"}
                )
            else:
                conflicts.append(
                    {
                        "path": path,
                        "reason": "upstream_changed_project_removed_file",
                    }
                )
            continue
        if _matches(current, wanted):
            unchanged.append(path)
            continue
        if _matches(current, prior):
            updates.append(_write(path, wanted))
            continue
        if (
            current["encoding"] != "utf-8"
            or prior.get("encoding", "utf-8") != "utf-8"
            or wanted.get("encoding", "utf-8") != "utf-8"
        ):
            conflicts.append({"path": path, "reason": "customized_binary_file"})
            continue
        merged = _merge_content(current["content"], prior["content"], wanted["content"])
        mode, mode_conflict = _merge_mode(current["mode"], prior["mode"], wanted["mode"])
        if merged["conflicted"] or mode_conflict:
            conflicts.append(
                {
                    "path": path,
                    "reason": "overlapping_customization",
                    "content_conflict": merged["conflicted"],
                    "mode_conflict": mode_conflict,
                }
            )
            continue
        merged_content = merged["content"]
        if merged_content == current["content"] and mode == current["mode"]:
            unchanged.append(path)
        else:
            updates.append(
                {
                    "path": path,
                    "content": merged_content,
                    "mode": mode,
                    "encoding": "utf-8",
                    "sha256": _sha256_bytes(merged_content.encode("utf-8")),
                }
            )

    for path in sorted(set(old) - set(new)):
        current = file_state(repo_root / path)
        if current is not None:
            retained.append({"path": path, "reason": "removed_upstream_project_keeps_file"})
    return _plan(creates, updates, unchanged, conflicts, retained)


def file_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PackMergeError(f"Pack target cannot be read: {path}: {exc}") from exc
    try:
        content = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = base64.b64encode(raw).decode("ascii")
        encoding = "base64"
    return {
        "content": content,
        "sha256": _sha256_bytes(raw),
        "encoding": encoding,
        "mode": stat.S_IMODE(path.stat().st_mode),
    }


def _merge_content(current: str, base: str, incoming: str) -> dict[str, Any]:
    if current == base:
        return {"content": incoming, "conflicted": False}
    if incoming == base or current == incoming:
        return {"content": current, "conflicted": False}
    with tempfile.TemporaryDirectory(prefix="yoke-pack-merge-") as raw:
        root = Path(raw)
        current_path = root / "current"
        base_path = root / "base"
        incoming_path = root / "incoming"
        current_path.write_text(current, encoding="utf-8")
        base_path.write_text(base, encoding="utf-8")
        incoming_path.write_text(incoming, encoding="utf-8")
        result = subprocess.run(
            [
                "git", "merge-file", "-p", "--diff3",
                str(current_path), str(base_path), str(incoming_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode not in (0, 1):
        raise PackMergeError(result.stderr.strip() or "git merge-file failed")
    return {"content": result.stdout, "conflicted": result.returncode == 1}


def _merge_mode(current: int, base: int, incoming: int) -> tuple[int, bool]:
    if current == base:
        return incoming, False
    if incoming == base or current == incoming:
        return current, False
    return current, True


def _matches(current: Mapping[str, Any], desired: Mapping[str, Any]) -> bool:
    return current["sha256"] == desired["sha256"] and current["mode"] == desired["mode"]


def _write(path: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": path,
        "content": entry["content"],
        "encoding": entry.get("encoding", "utf-8"),
        "sha256": entry["sha256"],
        "mode": entry["mode"],
    }


def _plan(
    creates: list[dict[str, Any]],
    updates: list[dict[str, Any]],
    unchanged: list[str],
    conflicts: list[dict[str, Any]],
    retained: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "creates": creates,
        "updates": updates,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "retained_project_files": retained,
        "changed": bool(creates or updates),
    }


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


__all__ = ["PackMergeError", "file_state", "plan_get", "plan_update"]
