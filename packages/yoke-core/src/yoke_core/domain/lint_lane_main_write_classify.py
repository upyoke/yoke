"""Classification helpers for the lane-main-write guard."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Sequence

from yoke_core.domain.file_line_check import classify_path
from yoke_core.domain.lint_lane_main_write_messages import ESCAPE_TOKEN, SUPPRESSION_TOKEN
from yoke_core.domain.lint_session_cwd_path_authority import (
    is_free_path,
    is_inside_control_plane,
    repo_root_from_worktree_path,
    resolve_for_display,
)
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)
from yoke_core.domain.project_identity_item_ref import item_ref_for_id
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_payload_command,
    extract_payload_targets,
)
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

_WRITE_TOOLS = frozenset({"Write", "Edit", "apply_patch"})

_UNTRACKED_GENERATED_VIEW_PATTERNS = (
    re.compile(r"(?:^|/)\.yoke/BOARD\.md(?:\.ts)?$"),
)

_BASH_WRITE_VERB_RE = re.compile(
    r"(?:^|[;&|]\s*|\s)(?:touch|mkdir|cp|mv|install|tee|truncate|sponge|patch)\b"
)


def command_has_suppression_token(text: str) -> bool:
    return isinstance(text, str) and SUPPRESSION_TOKEN in text


def command_has_escape_token(text: str) -> bool:
    return isinstance(text, str) and ESCAPE_TOKEN in text


def payload_has_escape_token(payload: dict) -> bool:
    parts = []
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            for field in ("command", "cmd", "file_path", "new_string", "old_string", "content"):
                part = value.get(field)
                if isinstance(part, str):
                    parts.append(part)
    for key in ("command",):
        part = payload.get(key)
        if isinstance(part, str):
            parts.append(part)
    return any(command_has_escape_token(part) for part in parts)


def is_write_tool_name(tool_name: str) -> bool:
    return tool_name in _WRITE_TOOLS


def is_untracked_generated_view(repo_relative: str) -> bool:
    normalized = repo_relative.replace("\\", "/")
    return any(pat.search(normalized) for pat in _UNTRACKED_GENERATED_VIEW_PATTERNS)


def is_generated_view_write(target: str, repo_root: str) -> bool:
    if is_untracked_generated_view(target):
        return True
    try:
        rel = str(Path(target).resolve().relative_to(Path(repo_root).resolve()))
    except (OSError, ValueError):
        rel = target.replace("\\", "/")
        if rel.startswith(repo_root):
            rel = rel[len(repo_root):].lstrip(os.sep)
        else:
            return False
    rel_posix = rel.replace("\\", "/")
    if is_untracked_generated_view(rel_posix):
        return True
    try:
        return classify_path(
            rel_posix, repo_root=Path(repo_root),
        ).value == "generated"
    except Exception:
        return False


def _is_scratch_free_path(
    target: str,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
) -> bool:
    """True when ``target`` is allowlist scratch, not project source."""
    if not is_free_path(target):
        return False
    from yoke_core.domain.lint_session_cwd_path_authority import is_inside
    for claim in claims:
        if is_inside(target, claim.worktree_path):
            return False
    for root in repo_roots:
        if is_inside_control_plane(target, root):
            return False
    return True


def matching_claim_for_main_target(
    target: str,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
) -> Optional[ClaimedWorktree]:
    for claim in claims:
        root = repo_root_from_worktree_path(claim.worktree_path)
        if root and is_inside_control_plane(target, root):
            return claim
    for root in repo_roots:
        if is_inside_control_plane(target, root):
            for claim in claims:
                if repo_root_from_worktree_path(claim.worktree_path) == root:
                    return claim
            if claims:
                return claims[0]
    return None


def lane_equivalent_path(main_target: str, claim: ClaimedWorktree) -> str:
    root = repo_root_from_worktree_path(claim.worktree_path)
    if not root:
        return claim.worktree_path
    try:
        rel = Path(main_target).resolve().relative_to(Path(root).resolve())
        return str((Path(claim.worktree_path) / rel).resolve())
    except (OSError, ValueError):
        return claim.worktree_path


def item_label(claim: ClaimedWorktree) -> str:
    ref = item_ref_for_id(int(claim.item_id))
    if claim.task_num is not None:
        return f"{ref} (T{claim.task_num})"
    return ref


def is_write_operation(tool_name: str, payload: dict) -> bool:
    if is_write_tool_name(tool_name):
        return True
    if tool_name != "Bash":
        return False
    command = extract_payload_command(payload)
    if not command:
        return False
    if match_read_only_signature(command):
        return False
    if extract_payload_targets(payload):
        return True
    return _bash_has_write_verb(command)


def _bash_has_write_verb(command: str) -> bool:
    if _BASH_WRITE_VERB_RE.search(command):
        return True
    return bool(re.search(r"(?:^|[;&|]\s*|\s)git\s+(?:commit|add|mv|rm)\b", command))


def collect_main_write_targets(
    *,
    tool_name: str,
    payload: dict,
    fallback_cwd: str,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
) -> list[tuple[str, ClaimedWorktree]]:
    """Return ``(main_target, claim)`` pairs that should be refused."""
    if not is_write_operation(tool_name, payload):
        return []

    raw_targets = list(extract_payload_targets(payload))
    if not raw_targets and fallback_cwd.strip():
        raw_targets = [fallback_cwd]

    hits: list[tuple[str, ClaimedWorktree]] = []
    seen: set[str] = set()
    for raw in raw_targets:
        if not isinstance(raw, str) or not raw.strip():
            continue
        if _is_scratch_free_path(raw, claims, repo_roots):
            continue
        claim = matching_claim_for_main_target(raw, claims, repo_roots)
        if claim is None:
            continue
        root = repo_root_from_worktree_path(claim.worktree_path) or ""
        if root and is_generated_view_write(raw, root):
            continue
        display = resolve_for_display(raw)
        if display in seen:
            continue
        seen.add(display)
        hits.append((display, claim))
    return hits


__all__ = [
    "collect_main_write_targets",
    "command_has_escape_token",
    "command_has_suppression_token",
    "is_write_operation",
    "is_write_tool_name",
    "item_label",
    "lane_equivalent_path",
    "matching_claim_for_main_target",
    "payload_has_escape_token",
    "_is_scratch_free_path",
]
