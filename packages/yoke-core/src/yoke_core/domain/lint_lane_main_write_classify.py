"""Classification helpers for the lane-main-write guard."""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Any, Mapping, Sequence

from yoke_contracts.hook_runner.client_facts import live_worktrees, write_target
from yoke_contracts.hook_runner.session_cwd import client_machine_home
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell

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


def is_yoke_adapter_command(command: str | ShellParse) -> bool:
    """True when every shell segment is a ``yoke`` CLI adapter invocation."""
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    if parsed.unparsed or not parsed.segments:
        return False
    return all(segment.program == "yoke" for segment in parsed.segments)


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


def is_write_operation(
    tool_name: str, payload: dict, shell: ShellParse | None = None
) -> bool:
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
    parsed = shell if shell is not None else parse_shell(command)
    if payload_has_embedded_python_write(payload, parsed):
        return True
    analysis = analyze_payload_write_targets(payload, shell=parsed)
    if analysis.targets or analysis.unresolved_variable:
        return True
    from yoke_core.domain.lint_shell_path_use import analyze_shell_path_use

    return analyze_shell_path_use(parsed).direct_write


def _client_target(
    payload: Mapping[str, Any], raw: str, fallback_cwd: str
) -> tuple[str, bool]:
    """Return ``(path, ignored)`` for one operand.

    A relative operand resolves against ``fallback_cwd`` — the command's
    declared workdir, then its leading ``cd`` statements, newline-joined
    included — the same answer the shell-path guard uses. An operand in a
    segment a later ``cd`` moved arrives already joined to that directory.
    The client's own resolution (``~``, symlinks, its checkout's ignore
    rules and Git metadata; see :func:`~yoke_contracts.hook_runner.client_facts.write_target`)
    is used only when it names that same path, so a client that missed the
    command's directory cannot move the write onto main. An operand without
    an agreeing client answer is treated as tracked, so an unanswered
    question leaves the guard protecting.
    """
    fact = write_target(payload, raw)
    client_path = fact.get("path") if fact is not None else None
    client = (
        (client_path, fact.get("ignored") is True)
        if isinstance(client_path, str)
        else None
    )
    target = expand_machine_home(raw, machine_home=client_machine_home(payload))
    if target.startswith("~"):
        # No client home: only the client can say where this names.
        return client or (target, False)
    if os.path.isabs(target) or not fallback_cwd.strip():
        return client or (os.path.normpath(target), False)
    target = os.path.normpath(os.path.join(fallback_cwd, target))
    if client is not None and client[0] == target:
        return client
    return target, False


def collect_main_write_targets(
    *,
    tool_name: str,
    payload: dict,
    fallback_cwd: str,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
    shell: ShellParse | None = None,
    segment_cwds: Sequence[str] = (),
) -> list[derivation.MainWriteHit]:
    """Return the refusable targets plus the derivation behind each one.

    Cwd alone is never a write target. Fallback to cwd only when a real
    Bash write shape has no extractable path (relative ``touch file``);
    the hit records that fallback so the refusal can name it instead of
    presenting cwd as a path the call itself asked for.
    """
    if not is_write_operation(tool_name, payload, shell):
        return []

    analysis = analyze_payload_write_targets(
        payload,
        protected_roots=tuple(repo_roots),
        shell=shell,
        segment_cwds=segment_cwds,
    )
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
            # Client-proven Git metadata, ignored paths and generated views
            # are outside this source-write guard; other guards still apply.
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
