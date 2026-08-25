"""Classification helpers for the lane-main-write guard."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import List, Sequence

from yoke_core.domain import lint_lane_main_write_derivation as derivation
from yoke_core.domain.file_line_check import classify_path
from yoke_core.domain.lint_lane_main_write_messages import ESCAPE_TOKEN, SUPPRESSION_TOKEN
from yoke_core.domain.lint_lane_main_write_lanes import matching_claim_for_main_target
from yoke_core.domain.lint_session_cwd_path_authority import (
    is_free_path,
    is_inside,
    is_inside_control_plane,
    repo_root_from_worktree_path,
    resolve_for_display,
)
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    GIT_MUTATING_SUBS,
    git_subcommand,
    match_read_only_signature,
)
from yoke_core.domain.project_identity_item_ref import item_ref_for_id
from yoke_core.domain.lint_session_cwd_target_extract import (
    SHELL_WRITE_COMMAND_BASES,
    analyze_payload_write_targets,
    extract_payload_command,
    payload_has_embedded_python_write,
    _split_redirect_targets,
)
from yoke_core.domain.lint_shell_target_tokens import shell_command_segments
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

_WRITE_TOOLS = frozenset({"Write", "Edit", "apply_patch"})

_UNTRACKED_GENERATED_VIEW_PATTERNS = (
    re.compile(r"(?:^|/)\.yoke/BOARD\.md(?:\.ts)?$"),
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
    for claim in claims:
        if is_inside(target, claim.worktree_path):
            return False
    for root in repo_roots:
        if is_inside_control_plane(target, root):
            return False
    return True


def item_label(claim: ClaimedWorktree) -> str:
    ref = item_ref_for_id(int(claim.item_id))
    if claim.task_num is not None:
        return f"{ref} (T{claim.task_num})"
    return ref


def _safe_split(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _strip_env_prefixes(tokens: List[str]) -> List[str]:
    out = list(tokens)
    while out and "=" in out[0] and not out[0].startswith("-"):
        head = out[0].split("=", 1)[0]
        if head and head.replace("_", "").isalnum() and head[0].isalpha():
            out = out[1:]
            continue
        break
    return out


def _segment_command_base(tokens: List[str]) -> str:
    stripped = _strip_env_prefixes(tokens)
    for tok in stripped:
        if not tok.startswith("-"):
            return tok.rsplit("/", 1)[-1]
    return ""


def _bash_has_file_redirect(command: str) -> bool:
    _clean, targets = _split_redirect_targets(_safe_split(command))
    return bool(targets)


def _bash_has_write_verb(command: str) -> bool:
    """True when a segment's leading command is a filesystem write verb."""
    for segment in shell_command_segments(command):
        base = _segment_command_base(segment)
        if base in SHELL_WRITE_COMMAND_BASES:
            return True
        if base == "git":
            if git_subcommand(_strip_env_prefixes(segment)) in GIT_MUTATING_SUBS:
                return True
    return False


def is_yoke_adapter_command(command: str) -> bool:
    """True when every shell segment is a ``yoke`` CLI adapter invocation."""
    if not command or not command.strip():
        return False
    segments = shell_command_segments(command)
    if not segments:
        return False
    return all(_segment_command_base(seg) == "yoke" for seg in segments)


def lane_path_exists_on_disk(claim: ClaimedWorktree) -> bool:
    """True when the claim's recorded lane directory is present locally."""
    raw = (claim.worktree_path or "").strip()
    if not raw:
        return False
    try:
        return Path(raw).is_dir()
    except OSError:
        return False


def is_write_operation(tool_name: str, payload: dict) -> bool:
    """True only for direct filesystem write shapes into a path target.

    Registered ``yoke <subcommand>`` adapters are control-plane calls and
    never count as tracked-source writes unless the shell body itself
    carries a file redirect. Path-shaped arguments alone (``ls /repo``)
    are not writes — only Edit/Write tools, write-verb command bases,
    shell file redirects, and embedded Python writes qualify. A heredoc
    is not itself a write.
    """
    if is_write_tool_name(tool_name):
        return True
    if tool_name != "Bash":
        return False
    command = extract_payload_command(payload)
    if not command:
        return False
    if payload_has_embedded_python_write(payload):
        return True
    if _bash_has_file_redirect(command):
        return True
    if match_read_only_signature(command):
        return False
    if is_yoke_adapter_command(command):
        return False
    return _bash_has_write_verb(command)


def collect_main_write_targets(
    *,
    tool_name: str,
    payload: dict,
    fallback_cwd: str,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
) -> list[derivation.MainWriteHit]:
    """Return the refusable targets plus the derivation behind each one.

    Cwd alone is never a write target. Fallback to cwd only when a real
    Bash write shape has no extractable path (relative ``touch file``);
    the hit records that fallback so the refusal can name it instead of
    presenting cwd as a path the call itself asked for.
    """
    if not is_write_operation(tool_name, payload):
        return []

    analysis = analyze_payload_write_targets(payload)
    raw_targets = list(analysis.targets)
    fell_back_to_cwd = False
    if (
        not raw_targets
        and not analysis.unresolved_variable
        and tool_name == "Bash"
        and fallback_cwd.strip()
    ):
        # A body whose only write operand was an unresolvable variable is
        # excluded — cwd would answer for a path we already established we
        # cannot resolve.
        raw_targets = [fallback_cwd]
        fell_back_to_cwd = True

    context = derivation.derivation_context(
        fallback_cwd, is_write_tool_name(tool_name), fell_back_to_cwd,
        analysis.unresolved_writes,
    )
    hits: list[derivation.MainWriteHit] = []
    seen: set[str] = set()
    for raw in raw_targets:
        if not isinstance(raw, str) or not raw.strip():
            continue
        target = raw
        if not os.path.isabs(target) and fallback_cwd.strip():
            target = os.path.join(fallback_cwd, target)
        target = resolve_for_display(target)
        claim = matching_claim_for_main_target(target, claims, repo_roots)
        if claim is None:
            continue
        root = repo_root_from_worktree_path(claim.worktree_path) or ""
        if root and is_generated_view_write(target, root):
            continue
        display = resolve_for_display(target)
        if display in seen:
            continue
        seen.add(display)
        hits.append(derivation.build_hit(display, claim, raw, root, context))
    return hits


__all__ = [
    "collect_main_write_targets",
    "command_has_escape_token",
    "command_has_suppression_token",
    "is_write_operation",
    "is_write_tool_name",
    "is_yoke_adapter_command",
    "item_label",
    "lane_path_exists_on_disk",
    "payload_has_escape_token",
    "_is_scratch_free_path",
]
