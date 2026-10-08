"""Shell-command target extraction for the session-cwd lint."""

from __future__ import annotations

import re
import shlex
from typing import List, Mapping, Optional, Tuple

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
    command_operand_tokens,
    path_target_from_token,
    resolve_path_operands,
    shell_command_segments,
    shell_variable_bindings,
)


FLAG_BINARY = frozenset({"-C", "--rootdir", "--target-root", "--worktree-path", "-w"})
FLAG_EQUALS_PREFIXES = (
    "--rootdir=",
    "--target-root=",
    "--worktree-path=",
    "--log-group-name=",
    "--log-group=",
)


def resolve_operand_targets(
    command: str,
    *,
    bindings: Optional[Mapping[str, str]] = None,
) -> Tuple[List[str], bool]:
    """Resolve generic local operands with the existing tokenizer.

    Flags and absolute positionals retain their existing semantics. Remote
    argv is omitted; shell redirects stay local. Unresolved operands report
    uncertainty instead of manufacturing a cwd target.
    """
    sanitized = strip_heredoc_body_lines(command)
    if not _safe_split(sanitized):
        return [], False
    if bindings is None:
        bindings = shell_variable_bindings(command)

    out: List[str] = extract_gh_repo_selector_targets(sanitized)
    unresolved = False
    for segment in shell_command_segments(sanitized):
        targets, segment_unresolved = _extract_segment_targets(segment, bindings)
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


_SED_SCRIPT_FLAGS = ("-e", "-f", "--expression", "--file")
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


def _sed_script_positional_index(command_base: str, tokens: List[str]) -> int:
    """Index of the positional that is an inline ``sed`` script, or ``-1``."""
    if command_base != "sed":
        return -1
    for tok in tokens[1:]:
        if tok in _SED_SCRIPT_FLAGS or tok.startswith("-e") or tok.startswith("-f"):
            return -1
    return 0


def _extract_segment_targets(
    tokens: List[str],
    bindings: Mapping[str, str],
) -> Tuple[List[str], bool]:
    """Extract target paths from a single command segment."""
    tokens = strip_env_prefixes(command_operand_tokens(tokens))
    if not tokens:
        return [], False

    command_base = _segment_command_base(tokens)
    if _is_yoke_payload_path_segment(command_base, tokens):
        return [], False
    remote_resource_indexes = _remote_resource_indexes(command_base, tokens)
    is_search = command_base in _SEARCH_COMMANDS
    skip_arg_targets = is_search or command_base in STDOUT_REPORTERS
    sed_script_index = _sed_script_positional_index(command_base, tokens)

    out: List[str] = []
    unresolved = False
    seen_command_name = False
    positional_index = -1

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
        if i in remote_resource_indexes:
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
            positional_index += 1
            if not skip_arg_targets and positional_index != sed_script_index:
                target = path_target_from_token(tok, bindings)
                if target is not None:
                    out.append(target)
        i += 1

    return out, unresolved


def _safe_split(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


_HEREDOC_OPENER_RE = re.compile(
    r"""<<(?P<dash>-?)\s*"""
    r"""(?:'(?P<sq>[^']*)'"""
    r"""|\"(?P<dq>[^\"]*)\""""
    r"""|\\?(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"""
)


def _partition_heredocs(command: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Return shell syntax plus ``(opener, body)`` heredoc sections."""
    lines = command.splitlines()
    out: List[str] = []
    sections: List[Tuple[str, str]] = []
    pending_tag: Optional[str] = None
    dash_form: bool = False
    opener = ""
    body: List[str] = []
    for line in lines:
        if pending_tag is None:
            out.append(line)
            tag, dash = _scan_heredoc_opener(line)
            if tag is not None:
                pending_tag = tag
                dash_form = dash
                opener = line
                body = []
            continue
        candidate = line.lstrip("\t") if dash_form else line
        if candidate.strip() == pending_tag:
            sections.append((opener, "\n".join(body)))
            pending_tag = None
            dash_form = False
            opener = ""
            body = []
            continue
        body.append(line.lstrip("\t") if dash_form else line)
    if pending_tag is not None:
        sections.append((opener, "\n".join(body)))
    return "\n".join(out), sections


def strip_heredoc_body_lines(command: str) -> str:
    """Drop heredoc body lines (and closing-tag lines) from ``command``."""
    return _partition_heredocs(command)[0]


def extract_heredoc_sections(command: str) -> List[Tuple[str, str]]:
    """Return heredoc opener/body pairs without interpreting body text."""
    return _partition_heredocs(command)[1]


def strip_heredoc_syntax(command: str) -> str:
    """Drop heredoc bodies and opener operators, preserving other commands."""
    shell, sections = _partition_heredocs(command)
    for opener, _body in sections:
        cleaned = _HEREDOC_OPENER_RE.sub("", opener, count=1)
        shell = shell.replace(opener, cleaned, 1)
    return shell


def _scan_heredoc_opener(line: str) -> Tuple[Optional[str], bool]:
    match = _HEREDOC_OPENER_RE.search(line)
    if match is None:
        return None, False
    tag = match.group("sq") or match.group("dq") or match.group("bare")
    return tag, bool(match.group("dash"))


def strip_env_prefixes(tokens: List[str]) -> List[str]:
    """Drop leading ``FOO=bar`` env-assignment tokens prepended to a command."""
    out = list(tokens)
    while out and "=" in out[0] and not out[0].startswith("-"):
        head = out[0].split("=", 1)[0]
        if head and head.replace("_", "").isalnum() and head[0].isalpha():
            out = out[1:]
            continue
        break
    return out


__all__ = [
    "FLAG_BINARY",
    "FLAG_EQUALS_PREFIXES",
    "REDIRECT_OPERATORS",
    "STDOUT_REPORTERS",
    "extract_command_targets",
    "extract_heredoc_sections",
    "resolve_command_targets",
    "strip_heredoc_body_lines",
    "strip_env_prefixes",
    "strip_heredoc_syntax",
]
