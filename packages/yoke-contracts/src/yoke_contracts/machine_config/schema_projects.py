"""Project-entry contract + shared issue primitives.

Sibling of :mod:`machine_config_contract` (split under the authored-file
cap). Hosts :class:`ValidationIssue` and the small string/issue helpers
too, so the dependency stays one-directional: the contract front door
imports from here and re-exports; this module imports nothing back.

Project ids are numbered per universe (each connection env's ``projects``
table starts at 1), so ``projects`` is a flat list of ``{checkout,
project_id, env, board?}`` entries. The same checkout appears once per env
it lives in — the rows are identical apart from ``env`` (and any per-env
id). Resolution matches a checkout AND the active/requested env. A bare
untagged entry (legacy, pre-stamp) resolves only under the active env.
A legacy checkout-keyed object is still read (normalized to the list form).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from yoke_contracts.machine_config.schema_connections import (
    MachineConfigContractError,
    selected_env,
)


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
    *,
    env: str | None,
) -> dict[str, Any]:
    """Return the resolved project entry for a checkout under ``env``.

    Resolution is env-scoped: an entry contributes its project id only for
    the env it is tagged with, so a per-universe id never resolves against
    the wrong universe. The returned entry is flattened to ``{project_id,
    env?, board?}`` (no ``checkout``) so existing readers keep working. An
    untagged legacy entry resolves only under ``active_env`` (or by path
    alone when there is no env context), which keeps reads working before the
    config is stamped. Returns ``{}`` when nothing matches.
    """
    active = str(payload.get("active_env") or "").strip()
    candidates = {_path_key(p) for p in checkout_path_candidates(repo_root)}
    for entry in normalize_projects(payload.get("projects")):
        checkout = Path(entry["checkout"]).expanduser()
        if _path_key(checkout) not in candidates:
            continue
        if entry_resolves_under_env(entry, env=env, active_env=active):
            return _flatten_entry(entry)
    return {}


def mapped_checkouts(
    payload: Mapping[str, Any],
    *,
    explicit_env: str | None = None,
) -> list[tuple[str, int]]:
    """Return ``(checkout, project_id)`` pairs for the resolved env.

    Project ids belong to a universe, so only rows matching the selected
    connection env contribute. An untagged legacy row resolves under the active
    env, or by path alone when no env can be resolved.
    """
    try:
        env: str | None = selected_env(payload, explicit_env=explicit_env)
    except MachineConfigContractError:
        env = None
    active = str(payload.get("active_env") or "").strip()
    pairs: list[tuple[str, int]] = []
    for entry in normalize_projects(payload.get("projects")):
        project_id = entry_project_id_for_env(entry, env=env, active_env=active)
        if project_id is not None:
            pairs.append((entry["checkout"], project_id))
    return pairs


def normalize_projects(projects: Any) -> list[dict[str, Any]]:
    """Return ``projects`` as a clean list of ``{checkout, project_id, env?, board?}``.

    Accepts the flat list shape and the legacy checkout-keyed object shape
    (``{checkout: {project_id, env?, board?}}``). Malformed rows are dropped;
    validation reports them separately against the raw payload.
    """
    out: list[dict[str, Any]] = []
    for checkout, raw in _iter_raw_projects(projects):
        if not _is_nonempty_str(checkout) or not isinstance(raw, Mapping):
            continue
        project_id = normalize_project_id(raw.get("project_id"))
        if project_id is None:
            continue
        entry: dict[str, Any] = {
            "checkout": str(checkout).strip(),
            "project_id": project_id,
        }
        env = raw.get("env")
        if _is_nonempty_str(env):
            entry["env"] = str(env).strip()
        board = _clean_board(raw.get("board"))
        if board:
            entry["board"] = board
        out.append(entry)
    return out


def _iter_raw_projects(projects: Any) -> Iterable[tuple[Any, Any]]:
    """Yield ``(checkout, raw_entry)`` pairs for either container shape."""
    if isinstance(projects, list):
        for raw in projects:
            if isinstance(raw, Mapping):
                yield raw.get("checkout"), raw
    elif isinstance(projects, Mapping):
        for checkout, raw in projects.items():
            yield checkout, raw


def entry_resolves_under_env(
    entry: Mapping[str, Any],
    *,
    env: str | None,
    active_env: str | None,
) -> bool:
    """Whether a normalized entry applies for the resolved connection env.

    A tagged entry applies only for its own env. An untagged legacy entry
    applies only under ``active_env`` — or by path alone when there is no env
    context (``env`` unresolved, or no ``active_env`` configured).
    """
    entry_env = entry.get("env")
    if _is_nonempty_str(entry_env):
        return env is not None and str(entry_env).strip() == str(env).strip()
    if env is None or not _is_nonempty_str(active_env):
        return True
    return str(env).strip() == str(active_env).strip()


def entry_project_id_for_env(
    entry: Mapping[str, Any],
    *,
    env: str | None,
    active_env: str | None,
) -> Optional[int]:
    """Return the project id a normalized entry contributes under ``env``."""
    if not entry_resolves_under_env(entry, env=env, active_env=active_env):
        return None
    return normalize_project_id(entry.get("project_id"))


def _flatten_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"project_id": entry["project_id"]}
    if _is_nonempty_str(entry.get("env")):
        out["env"] = str(entry["env"]).strip()
    board = _clean_board(entry.get("board"))
    if board:
        out["board"] = board
    return out


def upsert_project_entry(
    projects: Any,
    *,
    checkout: str,
    project_id: int,
    env: str | None = None,
    board: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the project list with the ``(checkout, env)`` row set to ``project_id``.

    The checkout's rows for *other* envs are left intact — a checkout appears
    once per env it lives in. But a given ``(env, project_id)`` slot belongs to
    exactly one checkout, so any *other* checkout claiming the same slot is
    dropped (the project moved). An untagged row's env is unknown, so it
    collides with any env for the same id.
    """
    checkout_key = _path_key(Path(str(checkout)).expanduser())
    env_key = str(env).strip() if _is_nonempty_str(env) else None
    target_id = int(project_id)
    kept: list[dict[str, Any]] = []
    for entry in normalize_projects(projects):
        same_checkout = _path_key(Path(entry["checkout"]).expanduser()) == checkout_key
        entry_env = (str(entry["env"]).strip()
                     if _is_nonempty_str(entry.get("env")) else None)
        if same_checkout and entry_env == env_key:
            continue  # replace this checkout's row for this env
        if (not same_checkout
                and entry["project_id"] == target_id
                and _env_collides(entry_env, env_key)):
            continue  # another checkout held this (env, project_id) slot
        kept.append(entry)
    new_entry: dict[str, Any] = {
        "checkout": str(checkout), "project_id": target_id,
    }
    if env_key is not None:
        new_entry["env"] = env_key
    clean_board = _clean_board(board)
    if clean_board:
        new_entry["board"] = clean_board
    kept.append(new_entry)
    return kept


def _env_collides(left: str | None, right: str | None) -> bool:
    """Whether two env labels occupy the same slot (equal, or either unknown)."""
    return left is None or right is None or left == right


def _clean_board(board: Any) -> dict[str, Any] | None:
    if not isinstance(board, Mapping):
        return None
    clean = {
        key: str(board[key]).strip()
        for key in ("render_path", "scope")
        if _is_nonempty_str(board.get(key))
    }
    return clean or None


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


def _warn(code: str, message: str, *, path: str = "", hint: str = "") -> ValidationIssue:
    return ValidationIssue("warning", code, message, path=path, hint=hint)
