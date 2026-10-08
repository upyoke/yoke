"""Operand roles shared by shell target extraction and authority guards.

This composes the existing tokenizer and operand/write resolvers. Capacity
inspection is a statvfs-style observation, not permission to read a directory
or its contents. Unknown syntax retains ordinary claim authority.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from yoke_core.domain.lint_shell_target_tokens import (
    command_operand_tokens,
    resolve_path_operands,
    shell_command_segments,
    shell_variable_bindings,
)
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    _extract_segment_targets,
    is_fd_duplication_target,
    strip_env_prefixes,
    strip_heredoc_syntax,
)
from yoke_core.domain.lint_session_cwd_remote_resources import remote_resource_indexes
from yoke_core.domain.path_claim_bash_splitter import split_pipeline


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

    @property
    def local_targets(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(u.path for u in self.uses if u.role != PathRole.REMOTE)
        )

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
    return base == "sed" and any(
        t.startswith("-i") or t.startswith("--in-place") for t in tokens[1:]
    )


def analyze_shell_path_use(
    command: str,
    *,
    bindings: Mapping[str, str] | None = None,
) -> ShellPathUse:
    """Retain operand roles while projecting existing local/write semantics."""
    from yoke_core.domain.lint_session_cwd_read_only_signatures import (
        GIT_MUTATING_SUBS,
        _match_simple,
        git_subcommand,
    )
    from yoke_core.domain.lint_session_cwd_target_extract import (
        SHELL_WRITE_COMMAND_BASES,
        resolve_shell_write_operands,
    )
    from yoke_core.domain.lint_session_cwd_gh_repo_selector import (
        extract_gh_repo_selector_targets,
    )

    if not isinstance(command, str) or not command.strip():
        return ShellPathUse(())
    bindings = shell_variable_bindings(command) if bindings is None else bindings
    sanitized = strip_heredoc_syntax(command)
    writes, unresolved_writes = resolve_shell_write_operands(command, bindings=bindings)
    uses = [
        PathUse(path, PathRole.UNKNOWN)
        for path in extract_gh_repo_selector_targets(sanitized)
    ]
    unresolved = unresolved_writes
    mutation = bool(writes) or unresolved_writes
    direct_write = mutation
    capacity_segments = []
    unsupported = False
    for segment in split_pipeline(sanitized):
        segments = shell_command_segments(segment)
        if not segments:
            capacity_segments.append(False)
            unsupported = True
            continue
        for raw_tokens in segments:
            tokens = strip_env_prefixes(command_operand_tokens(raw_tokens))
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
            targets, unknown = _extract_segment_targets(raw_tokens, bindings)
            unresolved = unresolved or unknown
            capacity = _capacity_operands(tokens, segment, bindings)
            capacity_segments.append(capacity is not None)
            state_move = (
                git_subcommand(tokens) in GIT_MUTATING_SUBS | _GIT_LOCAL_STATE_MOVES
                if base == "git"
                else _state_move(tokens, shlex.join(tokens))
            )
            if state_move:
                writes.extend(targets)
            # Compound Git keeps the established conservative lane judgment.
            lane_move = state_move or _state_move(tokens, command)
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
                if capacity is not None and target in capacity and target not in writes:
                    target_role = PathRole.CAPACITY
                uses.append(PathUse(target, target_role))
            if capacity is not None:
                uses.extend(PathUse(path, PathRole.CAPACITY) for path in capacity)
    uses.extend(PathUse(path, PathRole.WRITE) for path in writes)
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
    )


def is_capacity_target(path: str, uses: tuple[PathUse, ...]) -> bool:
    """A second use of the same path must never inherit inspection authority."""
    roles = {use.role for use in uses if use.path == path}
    return roles == {PathRole.CAPACITY}
