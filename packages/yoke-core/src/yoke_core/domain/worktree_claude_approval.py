"""Seed Claude's per-directory approval for linked worktree lanes."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


APPROVAL_FIELD = "hasTrustDialogAccepted"


@dataclass(frozen=True)
class ClaudeApprovalResult:
    """Outcome of copying an existing Claude directory approval."""

    source_path: str
    target_path: str
    seeded: bool = False
    already_approved: bool = False
    blocked_reason: str = ""
    write_error: str = ""

    @property
    def approved(self) -> bool:
        """Whether the target is known to be approved after this call."""
        return self.seeded or self.already_approved


def claude_config_path() -> Path:
    """Return the Claude state file used for directory approval."""
    explicit = os.environ.get("CLAUDE_CONFIG_PATH")
    if explicit:
        return Path(explicit).expanduser()
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser() / ".claude.json"
    return Path.home() / ".claude.json"


def seed_directory_approval(
    source_checkout: str,
    worktree_path: str,
    *,
    config_path: Optional[Path] = None,
) -> ClaudeApprovalResult:
    """Copy approval from an approved checkout to its linked worktree.

    Claude stores this state in a user-owned JSON file. The operation is
    deliberately conservative: it only writes when the source path is
    already approved, preserves every unrelated key, and is idempotent.
    """
    source = Path(source_checkout).expanduser().resolve()
    target = Path(worktree_path).expanduser().resolve()
    result = ClaudeApprovalResult(str(source), str(target))
    state_path = config_path.expanduser() if config_path else claude_config_path()

    try:
        with state_path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return _blocked(result, f"Claude state file not present: {state_path}")
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        return _blocked(result, f"Claude state file could not be read: {exc}")

    projects = state.get("projects") if isinstance(state, dict) else None
    if not isinstance(projects, dict):
        return _blocked(result, "Claude state has no projects directory map")

    source_record = projects.get(str(source))
    if not isinstance(source_record, dict):
        source_record = projects.get(str(Path(source_checkout).expanduser()))
    if not isinstance(source_record, dict) or source_record.get(APPROVAL_FIELD) is not True:
        return _blocked(result, f"source checkout is not Claude-approved: {source}")

    target_record = projects.get(str(target))
    if isinstance(target_record, dict) and target_record.get(APPROVAL_FIELD) is True:
        return ClaudeApprovalResult(str(source), str(target), already_approved=True)
    if target_record is None:
        target_record = {}
    if not isinstance(target_record, dict):
        return _blocked(result, f"Claude target directory record is not an object: {target}")

    target_record = dict(target_record)
    target_record[APPROVAL_FIELD] = True
    projects = dict(projects)
    projects[str(target)] = target_record
    next_state = dict(state)
    next_state["projects"] = projects

    try:
        _atomic_write_json(state_path, next_state)
    except OSError as exc:
        return _write_failed(result, f"could not update {state_path}: {exc}")
    return ClaudeApprovalResult(str(source), str(target), seeded=True)


def _blocked(result: ClaudeApprovalResult, reason: str) -> ClaudeApprovalResult:
    return ClaudeApprovalResult(
        result.source_path,
        result.target_path,
        blocked_reason=reason,
    )


def _write_failed(result: ClaudeApprovalResult, reason: str) -> ClaudeApprovalResult:
    return ClaudeApprovalResult(
        result.source_path,
        result.target_path,
        write_error=reason,
    )


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Replace a JSON state file without exposing a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


__all__ = [
    "APPROVAL_FIELD",
    "ClaudeApprovalResult",
    "claude_config_path",
    "seed_directory_approval",
]
