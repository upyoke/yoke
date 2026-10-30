"""Shell-command target extraction for the session-cwd lint."""

from __future__ import annotations

import os
import re
from typing import List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_core.domain.lint_shell_script_arguments import (
    gh_api_argument_roles,
    non_path_argument_indexes,
)

from yoke_core.domain.lint_session_cwd_gh_repo_selector import (
    extract_gh_repo_selector_targets,
)
from yoke_core.domain.lint_session_cwd_host_command import (
    yoke_subcommand_positionals,
)
from yoke_core.domain.lint_session_cwd_remote_resources import (
    remote_resource_indexes as _remote_resource_indexes,
)
from yoke_core.domain.lint_shell_target_tokens import (
    path_target_from_token,
    resolve_path_operands,
    shell_variable_bindings,
)


FLAG_BINARY = frozenset({"-C", "--rootdir", "--target-root", "--worktree-path", "-w"})
FLAG_EQUALS_PREFIXES = (
    "--rootdir=",
    "--target-root=",
    "--worktree-path=",
    "--log-group-name=",
    "--log-group=",
    "--name=",
    "--names=",
    "--path=",
)


def resolve_operand_targets(
    command: str | ShellParse,
    *,
    bindings: Optional[Mapping[str, str]] = None,
) -> Tuple[List[str], bool]:
    """Resolve generic local operands with the existing tokenizer.

    Flags and absolute positionals retain their existing semantics. Remote
    argv is omitted; shell redirects stay local. Unresolved operands report
    uncertainty instead of manufacturing a cwd target.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    if parsed.unparsed or not parsed.segments:
        return [], False
    if bindings is None:
        bindings = shell_variable_bindings(parsed.command)

    out: List[str] = extract_gh_repo_selector_targets(parsed.code)
    unresolved = False
    for segment in parsed.segments:
        targets, segment_unresolved = _extract_segment_targets(
            list(segment.argv), bindings
        )
        out.extend(targets)
        unresolved = unresolved or segment_unresolved
    return out, unresolved


def resolve_command_targets(command: str, *, bindings=None) -> Tuple[List[str], bool]:
    """Project local operands from the shared path-use analysis."""
    from yoke_core.domain.lint_shell_path_use import analyze_shell_path_use

    result = analyze_shell_path_use(command, bindings=bindings)
    return list(result.local_targets), result.unresolved


def extract_command_targets(
    command: str,
    *,
    bindings: Optional[Mapping[str, str]] = None,
) -> List[str]:
    """Return only the target paths :func:`resolve_command_targets` reads."""
    return resolve_command_targets(command, bindings=bindings)[0]


def in_segment_cwd(
    paths: Sequence[str], segment_cwds: Sequence[str], index: int
) -> List[str]:
    """Join relative ``paths`` to segment ``index``'s moved directory, if any."""
    cwd = segment_cwds[index] if index < len(segment_cwds) else ""
    return [
        os.path.normpath(os.path.join(cwd, path))
        if cwd and path and not os.path.isabs(path) and not path.startswith("~")
        else path
        for path in paths
    ]


def without_heredoc_operators(tokens: Sequence[str]) -> List[str]:
    """Drop heredoc operator words (``<<EOF``, ``<< 'EOF'``); bodies are input."""
    out: List[str] = []
    skip = False
    for token in tokens:
        opens = token.startswith("<<") and not token.startswith("<<<")
        if not skip and not opens:
            out.append(token)
        skip = opens and token in ("<<", "<<-")
    return out


_SEARCH_COMMANDS = frozenset(
    {
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "ripgrep",
        "ag",
        "ack",
    }
)
# Stdout reporters: operands are printed text, not filesystem write
# targets. Redirects on the same segment still extract as writes.
STDOUT_REPORTERS = frozenset({"print", "printf"})
_CURL_NON_PATH_VALUE_FLAGS = frozenset({"-w", "--write-out"})
# ``yoke`` control-plane registration adapters take path-shaped ARGUMENTS
# that are function payload — a row naming a path — not filesystem write
# targets; the engine validates its own mutations against claim authority.
# Denying them created an unrecoverable loop: repairing a wrong-repo lane
# registration requires naming the correct lane path, but the claim cannot
# cover that path until the registration lands. Only the named
# registration/repair shapes are exempt — file-writing yoke commands
# (watch captures, renders with ``--target-root``) keep full extraction.
_YOKE_PAYLOAD_PATH_SUBCOMMANDS = (("item-worktrees",), ("project", "register"))


def _is_yoke_payload_path_segment(command_base: str, tokens: List[str]) -> bool:
    """True when the segment is an exempt ``yoke`` registration adapter."""
    if command_base != "yoke":
        return False
    positionals = yoke_subcommand_positionals(tokens, limit=2)
    return any(
        tuple(positionals[: len(shape)]) == shape
        for shape in _YOKE_PAYLOAD_PATH_SUBCOMMANDS
    )


REDIRECT_OPERATORS = frozenset({">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>"})
#: The operand of a descriptor duplication or close -- ``2>&1``, ``>&2``,
#: ``2>&-``. Trailing shell punctuation is part of the match because a
#: redirect ending a substitution arrives glued to it (``$(... 2>&1)``).
_FD_DUP_OPERAND_RE = re.compile(r"^&(?:\d+|-)[);&]*$")


def is_fd_duplication_target(token: str) -> bool:
    """True when *token* duplicates or closes a descriptor, not a file.

    ``2>&1``, ``>&2`` and ``2>&-`` move a descriptor and write nothing,
    whether the operand arrives glued to the operator or separated from
    it. Either way it must never be resolved as a path: one that was
    became a phantom write target under the checkout root, denying a
    read-only inspection whose only redirect was ``2>&1``.
    """
    return bool(_FD_DUP_OPERAND_RE.match(token))


def is_file_redirect_operand(token: str) -> bool:
    """True when a redirect operand names a file the shell would write."""
    from yoke_core.domain.lint_session_cwd_path_authority import (
        is_dev_family_path,
    )

    return not is_dev_family_path(token) and not is_fd_duplication_target(token)


def _segment_command_base(tokens: List[str]) -> str:
    """Return the basename of the segment's leading command, or ``""``."""
    for tok in tokens:
        if not tok.startswith("-"):
            return tok.rsplit("/", 1)[-1]
    return ""


def _extract_segment_targets(
    tokens: List[str],
    bindings: Mapping[str, str],
) -> Tuple[List[str], bool]:
    """Extract target paths from one segment's argv (``ShellSegment.argv``)."""
    if not tokens:
        return [], False

    command_base = _segment_command_base(tokens)
    if _is_yoke_payload_path_segment(command_base, tokens):
        return [], False
    remote_resource_indexes = _remote_resource_indexes(command_base, tokens)
    from yoke_core.domain.lint_session_cwd_read_only_signatures import _classify_grep_like

    is_search = command_base in _SEARCH_COMMANDS and not (
        command_base == "rg" and _classify_grep_like(tokens) is None
    )
    skip_arg_targets = is_search or command_base in STDOUT_REPORTERS
    non_path_indexes = non_path_argument_indexes(command_base, tokens)
    _, file_arguments = gh_api_argument_roles(command_base, tokens)

    out: List[str] = []
    unresolved = False
    seen_command_name = False

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if command_base == "curl" and tok in _CURL_NON_PATH_VALUE_FLAGS:
            i += 2
            continue
        # Redirects are resolved before the remote-resource skip: the
        # shell performs them on THIS machine even when they trail a
        # remote invocation's argv, so ``host-command ... -- ls /x >
        # /local/out`` still surfaces the local destination.
        if tok in REDIRECT_OPERATORS:
            if i + 1 < n:
                target = path_target_from_token(tokens[i + 1], bindings)
                if target is not None:
                    out.append(target)
            i += 2
            continue
        if i in file_arguments:
            values, file_unresolved = resolve_path_operands([file_arguments[i]], bindings)
            out.extend(values)
            unresolved = unresolved or file_unresolved
            i += 1
            continue
        if i in remote_resource_indexes or i in non_path_indexes:
            i += 1
            continue
        if not skip_arg_targets:
            if tok in FLAG_BINARY and i + 1 < n:
                value = tokens[i + 1]
                if value and not value.startswith("-"):
                    values, flag_unresolved = resolve_path_operands([value], bindings)
                    out.extend(values)
                    unresolved = unresolved or flag_unresolved
                i += 2
                continue
            matched_equals = False
            for prefix in FLAG_EQUALS_PREFIXES:
                if tok.startswith(prefix):
                    value = tok[len(prefix) :]
                    if value:
                        values, eq_unresolved = resolve_path_operands([value], bindings)
                        out.extend(values)
                        unresolved = unresolved or eq_unresolved
                    matched_equals = True
                    break
            if matched_equals:
                i += 1
                continue
        if not seen_command_name and not tok.startswith("-"):
            seen_command_name = True
            i += 1
            continue
        if seen_command_name and not tok.startswith("-"):
            if not skip_arg_targets:
                target = path_target_from_token(tok, bindings)
                if target is None and tok.startswith("~"):
                    target = tok
                if target is not None:
                    out.append(target)
        i += 1

    return out, unresolved


__all__ = [
    "FLAG_BINARY",
    "FLAG_EQUALS_PREFIXES",
    "REDIRECT_OPERATORS",
    "STDOUT_REPORTERS",
    "extract_command_targets",
    "in_segment_cwd",
    "resolve_command_targets",
    "without_heredoc_operators",
]
