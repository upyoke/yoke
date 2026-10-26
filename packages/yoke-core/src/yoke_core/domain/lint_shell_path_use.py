"""Operand roles shared by shell target extraction and authority guards.

This composes the existing tokenizer and operand/write resolvers. Capacity
inspection is a statvfs-style observation, not permission to read a directory
or its contents. Unknown syntax retains ordinary claim authority.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_core.domain.lint_shell_target_tokens import (
    resolve_path_operands,
    shell_variable_bindings,
)
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    _extract_segment_targets,
    in_segment_cwd,
    is_fd_duplication_target,
    without_heredoc_operators,
)
from yoke_core.domain.lint_session_cwd_remote_resources import remote_resource_indexes


class PathRole(str, Enum):
    CAPACITY = "filesystem_capacity"
    READ = "filesystem_read"
    WRITE = "local_mutation"
    REMOTE = "remote_resource"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PathUse:
    path: str
    role: PathRole


@dataclass(frozen=True)
class ShellPathUse:
    uses: tuple[PathUse, ...]
    unresolved: bool = False
    unresolved_writes: bool = False
    mutation: bool = False
    inspection_only: bool = False
    direct_write: bool = False
    write_operands: tuple[str, ...] = ()
    operand_targets: tuple[str, ...] = ()

    @property
    def local_targets(self) -> tuple[str, ...]:
        return self.operand_targets

    @property
    def write_targets(self) -> tuple[str, ...]:
        return self.write_operands


_CAPACITY_OPTIONS = frozenset(
    {
        "--human-readable",
        "--si",
        "--portability",
        "--inodes",
        "--local",
        "--total",
    }
)
_CAPACITY_SHORT_OPTIONS = frozenset("khHPmgial")
_GIT_LOCAL_STATE_MOVES = frozenset(
    {
        "checkout",
        "restore",
        "reset",
        "clean",
        "switch",
        "fetch",
        "pull",
        "merge",
        "rebase",
        "cherry-pick",
        "revert",
        "stash",
    }
)
#: ``git stash`` actions that only read the stash stack.
_GIT_STASH_READS = frozenset({"list", "show"})


def _git_state_move(tokens: list[str]) -> bool:
    """True when this git invocation changes repository or worktree state."""
    from yoke_core.domain.lint_session_cwd_git_read_forms import (
        GIT_MUTATING_SUBS,
        GIT_READ_ONLY_SUBS,
        classify_git,
        git_subcommand_index,
    )

    index = git_subcommand_index(tokens)
    if index is None:
        return False
    if tokens[index] in GIT_READ_ONLY_SUBS:
        return classify_git(tokens) is None
    if tokens[index] == "stash":
        action = tokens[index + 1] if index + 1 < len(tokens) else ""
        return action not in _GIT_STASH_READS
    return tokens[index] in GIT_MUTATING_SUBS | _GIT_LOCAL_STATE_MOVES


def _capacity_operands(tokens: list[str], segment: str, bindings: Mapping[str, str]):
    """Recognize only the non-mutating df forms whose operands we can settle."""
    from yoke_core.domain.lint_session_cwd_target_extract import _split_redirect_targets

    if not tokens or tokens[0].rsplit("/", 1)[-1] != "df":
        return None
    if any(syntax in segment for syntax in ("$(", "`", "<")):
        return None
    clean, _redirects = _split_redirect_targets(tokens)
    operands = []
    after_options = False
    for token in clean[1:]:
        if ">" in token and is_fd_duplication_target(token.split(">", 1)[1]):
            continue
        if token == "--" and not after_options:
            after_options = True
            continue
        if not after_options and token.startswith("-"):
            if token in _CAPACITY_OPTIONS:
                continue
            if (
                token.startswith("--")
                or not token[1:]
                or not set(token[1:]) <= _CAPACITY_SHORT_OPTIONS
            ):
                return None
            continue
        operands.append(token)
    paths, unresolved = resolve_path_operands(operands, bindings)
    return None if unresolved else paths


def _state_move(tokens: list[str], command: str) -> bool:
    from yoke_core.domain.lint_session_cwd_foreign_lane import (
        is_read_only_git_inspection,
    )

    if not tokens:
        return False
    base = tokens[0].rsplit("/", 1)[-1]
    if base in {"rm", "rmdir", "unlink"}:
        return True
    if base == "git":
        return not is_read_only_git_inspection(command)
    if base in {"find", "rg"}:
        from yoke_core.domain.lint_session_cwd_read_only_signatures import _match_simple

        return _match_simple(command) is None
    return base == "sed" and any(
        t.startswith("-i") or t.startswith("--in-place") for t in tokens[1:]
    )


def analyze_shell_path_use(
    command: str | ShellParse,
    *,
    bindings: Mapping[str, str] | None = None,
    segment_cwds: Sequence[str] = (),
) -> ShellPathUse:
    """Retain operand roles; ``segment_cwds`` moves relative operands per segment."""
    from yoke_core.domain.lint_session_cwd_git_read_forms import (
        GIT_MUTATING_SUBS,
        git_subcommand,
    )
    from yoke_core.domain.lint_session_cwd_read_only_signatures import _match_simple
    from yoke_core.domain.lint_session_cwd_target_extract import (
        SHELL_WRITE_COMMAND_BASES,
        resolve_shell_write_operands,
    )
    from yoke_core.domain.lint_session_cwd_gh_repo_selector import (
        extract_gh_repo_selector_targets,
    )

    if not isinstance(command, ShellParse):
        command = parse_shell(command if isinstance(command, str) else "")
    parsed = command
    if not parsed.command.strip():
        return ShellPathUse(())
    if bindings is None:
        bindings = shell_variable_bindings(parsed.command)
    writes, unresolved_writes = resolve_shell_write_operands(
        parsed, bindings=bindings, segment_cwds=segment_cwds
    )
    uses = [
        PathUse(path, PathRole.UNKNOWN)
        for path in extract_gh_repo_selector_targets(parsed.code)
    ]
    local_targets = [use.path for use in uses]
    unresolved = unresolved_writes
    mutation = bool(writes) or unresolved_writes
    direct_write = mutation
    capacity_segments = [False for _statement in parsed.unparsed]
    unsupported = bool(parsed.unparsed)
    for index, segment in enumerate(parsed.segments):
        tokens = without_heredoc_operators(segment.argv)
        if not tokens:
            capacity_segments.append(False)
            unsupported = True
            continue
        base = tokens[0].rsplit("/", 1)[-1]
        direct_write = (
            direct_write
            or base in SHELL_WRITE_COMMAND_BASES
            or (base == "git" and git_subcommand(tokens) in GIT_MUTATING_SUBS)
        )
        remote = remote_resource_indexes(base, tokens)
        uses.extend(PathUse(tokens[i], PathRole.REMOTE) for i in sorted(remote))
        targets, unknown = _extract_segment_targets(tokens, bindings)
        targets = in_segment_cwd(targets, segment_cwds, index)
        local_targets.extend(targets)
        unresolved = unresolved or unknown
        capacity = _capacity_operands(tokens, segment.text, bindings)
        if capacity is not None:
            capacity = in_segment_cwd(capacity, segment_cwds, index)
        capacity_settled = capacity is not None and not any(
            any(mark in path for mark in "*?{[") for path in capacity
        )
        capacity_segments.append(capacity_settled)
        state_move = (
            _git_state_move(tokens)
            if base == "git"
            else _state_move(tokens, shlex.join(tokens))
        )
        if state_move:
            writes.extend(targets or in_segment_cwd(["."], segment_cwds, index))
        lane_move = state_move or _state_move(tokens, shlex.join(tokens))
        mutation = mutation or lane_move
        direct_write = direct_write or state_move
        role = (
            PathRole.READ if _match_simple(shlex.join(tokens)) else PathRole.UNKNOWN
        )
        if base == "cd" and len(tokens) == 2 and not tokens[1].startswith("-"):
            role = PathRole.READ
        if state_move:
            role = PathRole.WRITE
        # A read with no settled operands cannot borrow a preceding df exemption.
        unsupported = (
            unsupported
            or (
                capacity is None
                and not targets
                and base not in SHELL_WRITE_COMMAND_BASES
            )
            or (
                capacity is None
                and role == PathRole.UNKNOWN
                and base not in SHELL_WRITE_COMMAND_BASES
            )
        )
        for target in targets:
            target_role = PathRole.WRITE if target in writes else role
            if capacity_settled and target in capacity and target not in writes:
                target_role = PathRole.CAPACITY
            uses.append(PathUse(target, target_role))
        if capacity is not None:
            uses.extend(
                PathUse(
                    path,
                    PathRole.CAPACITY if capacity_settled else PathRole.UNKNOWN,
                )
                for path in capacity
            )
            local_targets.extend(path for path in capacity if path not in targets)
    uses.extend(PathUse(path, PathRole.WRITE) for path in writes)
    local_targets.extend(path for path in writes if path not in local_targets)
    if unsupported or unresolved:
        uses = [
            PathUse(
                use.path,
                PathRole.UNKNOWN if use.role == PathRole.CAPACITY else use.role,
            )
            for use in uses
        ]
    return ShellPathUse(
        tuple(dict.fromkeys(uses)),
        unresolved,
        unresolved_writes,
        mutation,
        bool(capacity_segments)
        and all(capacity_segments)
        and not mutation
        and not unresolved,
        direct_write,
        tuple(dict.fromkeys(writes)),
        tuple(local_targets),
    )


def is_capacity_target(path: str, uses: tuple[PathUse, ...]) -> bool:
    """A second use of the same path must never inherit inspection authority."""
    roles = {use.role for use in uses if use.path == path}
    return roles == {PathRole.CAPACITY}
