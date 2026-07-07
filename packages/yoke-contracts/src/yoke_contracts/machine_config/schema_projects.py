"""Project-entry contract + shared issue primitives.

Sibling of :mod:`machine_config_contract` (split under the authored-file
cap). Hosts :class:`ValidationIssue` and the small string/issue helpers
too, so the dependency stays one-directional: the contract front door
imports from here and re-exports; this module imports nothing back.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    path: str = ""
    hint: str = ""
    def as_dict(self) -> dict[str, str]:
        data = {"severity": self.severity, "code": self.code,
                "message": self.message}
        if self.path:
            data["path"] = self.path
        if self.hint:
            data["hint"] = self.hint
        return data


def project_entry_for_checkout(
    payload: Mapping[str, Any],
    repo_root: str | Path,
) -> dict[str, Any]:
    """Return the project entry for a checkout, honoring worktree roots."""
    projects = payload.get("projects", {})
    if not isinstance(projects, Mapping):
        return {}
    candidates = {_path_key(p) for p in checkout_path_candidates(repo_root)}
    for key, value in projects.items():
        if isinstance(key, str) and _path_key(Path(key).expanduser()) in candidates:
            return dict(value) if isinstance(value, Mapping) else {}
    return {}


def checkout_path_candidates(repo_root: str | Path) -> list[Path]:
    root = Path(repo_root).expanduser()
    candidates = [root, *root.parents]
    try:
        candidates.append(root.resolve())
        candidates.extend(root.resolve().parents)
    except OSError:
        pass
    stripped = _strip_worktree_path(root)
    if stripped != root:
        candidates.append(stripped)
        try:
            candidates.append(stripped.resolve())
        except OSError:
            pass
    seen: set[str] = set()
    out: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            out.append(candidate)
            seen.add(key)
    return out


def normalize_project_id(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        project_id = int(value)
    except (TypeError, ValueError):
        return None
    return project_id if project_id > 0 else None


def canonical_project_entry(
    entry: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the supported project-entry shape, or ``None`` if invalid."""

    project_id = normalize_project_id(entry.get("project_id"))
    if project_id is None:
        return None
    out: dict[str, Any] = {"project_id": project_id}
    board = entry.get("board")
    if isinstance(board, Mapping):
        clean_board = {
            key: str(board[key]).strip()
            for key in ("render_path", "scope")
            if _is_nonempty_str(board.get(key))
        }
        if clean_board:
            out["board"] = clean_board
    return out


def canonical_project_map(
    projects: Mapping[str, Any],
    *,
    checkout: str,
    entry: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a repaired project map with one canonical entry per project id."""

    new_entry = canonical_project_entry(entry)
    if new_entry is None:
        raise ValueError("new project entry must carry a positive project_id")
    new_project_id = int(new_entry["project_id"])
    repaired: dict[str, Any] = {}
    for raw_checkout, raw_entry in projects.items():
        if not _is_nonempty_str(raw_checkout):
            continue
        if not isinstance(raw_entry, Mapping):
            continue
        existing = canonical_project_entry(raw_entry)
        if existing is None:
            continue
        if int(existing["project_id"]) == new_project_id:
            continue
        repaired[str(raw_checkout).strip()] = existing
    repaired[str(checkout)] = new_entry
    return repaired


def _validate_project_entry(checkout: Any, entry: Any) -> list[ValidationIssue]:
    prefix = f"projects.{checkout}"
    if not _is_nonempty_str(checkout):
        return [_error("project_checkout_invalid", "project checkout path must be a non-empty string", path="projects")]
    if not isinstance(entry, Mapping):
        return [_error("project_entry_invalid", "project entry must be an object", path=prefix)]
    issues: list[ValidationIssue] = []
    for key in sorted(set(entry) - {"project_id", "board"}):
        issues.append(_error("project_key_invalid",
                             f"project entry does not support {key!r}",
                             path=f"{prefix}.{key}"))
    if normalize_project_id(entry.get("project_id")) is None:
        issues.append(_error("project_id_required",
                             "project entry requires a positive integer project_id",
                             path=f"{prefix}.project_id"))
    board = entry.get("board")
    if board is not None:
        if not isinstance(board, Mapping):
            issues.append(_error("project_board_invalid",
                                 "project board must be an object",
                                 path=f"{prefix}.board"))
        else:
            allowed = {"render_path", "scope"}
            for key in sorted(set(board) - allowed):
                issues.append(_error("project_board_key_invalid",
                                     f"project board does not support {key!r}",
                                     path=f"{prefix}.board.{key}",
                                     hint="Use only render_path and scope. board-art is always .yoke/board-art."))
            for key in allowed:
                if key in board and not _is_nonempty_str(board.get(key)):
                    issues.append(_error("project_board_value_invalid",
                                         f"project board {key} must be a non-empty string",
                                         path=f"{prefix}.board.{key}"))
    return issues


def _strip_worktree_path(path: Path) -> Path:
    parts = list(path.parts)
    if ".worktrees" in parts:
        return Path(*parts[:parts.index(".worktrees")])
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees":
            return Path(*parts[:i])
    return path


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_str(value: Any, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _error(code: str, message: str, *, path: str = "", hint: str = "") -> ValidationIssue:
    return ValidationIssue("error", code, message, path=path, hint=hint)
