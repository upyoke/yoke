"""Classification helpers for the lane-main-write guard."""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
from typing import Any, List, Mapping, Sequence

from yoke_contracts.hook_runner.client_facts import live_worktrees, write_target
from yoke_contracts.hook_runner.session_cwd import client_machine_home

from yoke_core.domain import lint_lane_main_write_derivation as derivation
from yoke_contracts.project_contract.file_line_policy import (
    generated_path_globs,
    tracked_generated_views,
)
from yoke_core.domain.file_line_check_helpers import (
    GENERATED_PATH_PATTERNS,
    GENERATED_SENTINELS,
)
from yoke_core.domain.file_line_check_pack_versions import is_pack_manifest
from yoke_core.domain.lint_lane_main_write_messages import (
    ESCAPE_TOKEN,
    SUPPRESSION_TOKEN,
)
from yoke_core.domain.lint_lane_main_write_lanes import matching_claim_for_main_target
from yoke_core.domain.lint_session_cwd_home import expand_machine_home
from yoke_core.domain.lint_session_cwd_path_authority import (
    repo_root_from_worktree_path,
)
from yoke_core.domain.project_identity_item_ref import item_ref_for_id
from yoke_core.domain.lint_session_cwd_target_extract import (
    analyze_payload_write_targets,
    extract_payload_command,
    payload_has_embedded_python_write,
)
from yoke_core.domain.lint_shell_target_tokens import shell_command_segments
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

_WRITE_TOOLS = frozenset({"Write", "Edit", "apply_patch"})

_UNTRACKED_GENERATED_VIEW_PATTERNS = (re.compile(r"(?:^|/)\.yoke/BOARD\.md(?:\.ts)?$"),)


def command_has_suppression_token(text: str) -> bool:
    return isinstance(text, str) and SUPPRESSION_TOKEN in text


def command_has_escape_token(text: str) -> bool:
    return isinstance(text, str) and ESCAPE_TOKEN in text


def payload_has_escape_token(payload: dict) -> bool:
    parts = []
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            for field in (
                "command",
                "cmd",
                "file_path",
                "new_string",
                "old_string",
                "content",
            ):
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
    """True when *target* has the path shape of a generated file.

    Path shape only: the checkout lives on the client machine, so a rule
    that reads it (file content, an install manifest) is not one the
    authority can apply. Gitignored renders are excluded separately by the
    client's ignore answer.
    """
    if is_untracked_generated_view(target):
        return True
    root = repo_root.rstrip("/") + "/"
    if not target.startswith(root):
        return False
    rel = target[len(root) :].replace("\\", "/")
    return (
        is_untracked_generated_view(rel)
        or rel in tracked_generated_views()
        or rel in GENERATED_SENTINELS
        or is_pack_manifest(rel)
        or any(
            fnmatch.fnmatchcase(rel, pattern)
            for pattern in (*generated_path_globs(), *GENERATED_PATH_PATTERNS)
        )
    )


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


def is_yoke_adapter_command(command: str) -> bool:
    """True when every shell segment is a ``yoke`` CLI adapter invocation."""
    if not command or not command.strip():
        return False
    segments = shell_command_segments(command)
    if not segments:
        return False
    return all(_segment_command_base(seg) == "yoke" for seg in segments)


def lane_path_exists_on_disk(
    payload: Mapping[str, Any], claim: ClaimedWorktree
) -> bool:
    """True unless the client reported its worktrees and this lane is gone.

    The lane lives on the client machine, which lists the worktrees still
    present (:func:`~yoke_contracts.hook_runner.client_facts.live_worktrees`).
    Without that fact absence is unproven, so the lane counts as present.
    """
    raw = (claim.worktree_path or "").strip().rstrip("/")
    if not raw:
        return False
    live = live_worktrees(payload)
    if live is None:
        return True
    return raw in {path.rstrip("/") for path in live}


def is_write_operation(tool_name: str, payload: dict) -> bool:
    """True only for direct filesystem write shapes into a path target.

    Registered ``yoke <subcommand>`` adapters are control-plane calls and
    never count as tracked-source writes unless the shell body itself
    carries a file redirect. Path-shaped arguments alone (``ls /repo``)
    are not writes — only Edit/Write tools, write-verb command bases,
    shell file redirects (including a heredoc feeding ``>`` / ``>>`` /
    ``tee``), and embedded Python writes qualify. A heredoc is not
    itself a write; opener-line redirects still are, even when the
    body would not survive ``shlex.split``.
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
    analysis = analyze_payload_write_targets(payload)
    if analysis.targets or analysis.unresolved_variable:
        return True
    from yoke_core.domain.lint_shell_path_use import analyze_shell_path_use

    return analyze_shell_path_use(command).direct_write


def _client_target(
    payload: Mapping[str, Any], raw: str, fallback_cwd: str
) -> tuple[str, bool]:
    """Return ``(path, ignored)`` for one operand as the client resolved it.

    The client resolved ``~``, the command's cwd and symlinks on its own
    filesystem and asked its checkout's ignore rules
    (:func:`~yoke_contracts.hook_runner.client_facts.write_target`). An
    operand it did not report is joined to the cwd as written and treated
    as tracked, so an unanswered question leaves the guard protecting.
    """
    fact = write_target(payload, raw)
    if fact is not None and isinstance(fact.get("path"), str):
        return fact["path"], fact.get("ignored") is True
    target = expand_machine_home(raw, machine_home=client_machine_home(payload))
    if target.startswith("~"):
        return target, False  # no client home: names no path on any machine
    if not os.path.isabs(target) and fallback_cwd.strip():
        target = os.path.join(fallback_cwd, target)
    return os.path.normpath(target), False


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
        fallback_cwd,
        is_write_tool_name(tool_name),
        fell_back_to_cwd,
        analysis.unresolved_writes,
    )
    hits: list[derivation.MainWriteHit] = []
    seen: set[str] = set()
    for raw in raw_targets:
        if not isinstance(raw, str) or not raw.strip():
            continue
        target, ignored = _client_target(payload, raw, fallback_cwd)
        claim = matching_claim_for_main_target(target, claims, repo_roots)
        if claim is None:
            continue
        root = repo_root_from_worktree_path(claim.worktree_path) or ""
        if root and (is_generated_view_write(target, root) or ignored):
            # A generated view or an ignored path is not the tracked
            # source this guard protects, and both are written on main by
            # documented recipes.
            continue
        display = target
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
]
