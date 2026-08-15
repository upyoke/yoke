"""Shell-command target extraction for the session-cwd lint."""

from __future__ import annotations

import re
import shlex
from typing import List, Mapping, Optional, Tuple

from yoke_core.domain.lint_shell_target_tokens import (
    path_target_from_token,
    shell_variable_bindings,
)


FLAG_BINARY = frozenset({
    "-C",
    "--rootdir",
    "--target-root",
    "--worktree-path",
    "-w",
})

FLAG_EQUALS_PREFIXES = (
    "--rootdir=",
    "--target-root=",
    "--worktree-path=",
)


def extract_command_targets(
    command: str,
    *,
    bindings: Optional[Mapping[str, str]] = None,
) -> List[str]:
    """Return the target paths extracted from a Bash command body.

    Walks the tokens, surfaces ``-C <path>`` / ``--rootdir <path>`` /
    ``--target-root <path>`` / ``--worktree-path <path>`` / ``-w <path>``
    bindings and ``--flag=<path>`` short forms, plus absolute-path
    positional arguments that appear after the command name (skipping
    flags). Returns an empty list when no target signals appear — the
    caller treats that as "fall through to cwd".

    Heredoc bodies (``<<TAG`` / ``<<'TAG'`` / ``<<"TAG"`` / ``<<-TAG``)
    are stripped at the **line** level before ``shlex.split`` runs:
    only body lines and the closing-tag line are removed. Anything on
    the opener's own line — including a redirect target that comes
    after the opener (``cat <<EOF > /tmp/out``) — survives and is
    available to the positional walk below.

    A token naming a shell variable resolves through that variable's own
    assignment (see :mod:`lint_shell_target_tokens`). Pass ``bindings``
    when the assignment lives in a wider command body than ``command``
    — a caller walking one segment at a time would otherwise lose it.
    """
    sanitized = strip_heredoc_body_lines(command)
    tokens = _safe_split(sanitized)
    if not tokens:
        return []
    if bindings is None:
        bindings = shell_variable_bindings(command)

    out: List[str] = []
    for segment in _split_command_segments(tokens):
        out.extend(_extract_segment_targets(segment, bindings))
    return out


# Shell control operators that separate one command invocation from the
# next. ``extract_command_targets`` splits on these so each segment's
# leading token is recognised as that segment's command name.
_SEGMENT_SEPARATORS = frozenset({"&&", "||", "|", "|&", ";", ";;", "&"})

_SEARCH_COMMANDS = frozenset({
    "grep", "egrep", "fgrep", "rg", "ripgrep", "ag", "ack",
})

# ``yoke`` control-plane registration adapters take path-shaped ARGUMENTS
# that are function payload — a row naming a path — not filesystem write
# targets; the engine validates its own mutations against claim authority.
# Denying them created an unrecoverable loop: repairing a wrong-repo lane
# registration requires naming the correct lane path, but the claim cannot
# cover that path until the registration lands. Only the named
# registration/repair shapes are exempt — file-writing yoke commands
# (watch captures, renders with ``--target-root``) keep full extraction.
_YOKE_PAYLOAD_PATH_SUBCOMMANDS = (
    ("item-worktrees",),
    ("project", "register"),
)

# Yoke global flags that consume a value token; the value must not be
# mistaken for the subcommand when matching the exempt shapes above.
_YOKE_VALUE_FLAGS = frozenset({"--env", "--config", "--session-id"})


def _is_yoke_payload_path_segment(command_base: str, tokens: List[str]) -> bool:
    """True when the segment is an exempt ``yoke`` registration adapter."""
    if command_base != "yoke":
        return False
    positionals: List[str] = []
    seen_command = False
    i = 0
    while i < len(tokens) and len(positionals) < 2:
        tok = tokens[i]
        if tok in _YOKE_VALUE_FLAGS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if not seen_command:
            seen_command = True
            i += 1
            continue
        positionals.append(tok)
        i += 1
    return any(
        tuple(positionals[: len(shape)]) == shape
        for shape in _YOKE_PAYLOAD_PATH_SUBCOMMANDS
    )

_SED_SCRIPT_FLAGS = ("-e", "-f", "--expression", "--file")

REDIRECT_OPERATORS = frozenset({
    ">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>",
})


def _split_command_segments(tokens: List[str]) -> List[List[str]]:
    """Split a token stream into per-invocation segments on shell operators."""
    segments: List[List[str]] = []
    current: List[str] = []
    for tok in tokens:
        if tok in _SEGMENT_SEPARATORS:
            if current:
                segments.append(current)
            current = []
            continue
        current.append(tok)
    if current:
        segments.append(current)
    return segments


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
) -> List[str]:
    """Extract target paths from a single command segment."""
    tokens = strip_env_prefixes(tokens)
    if not tokens:
        return []

    command_base = _segment_command_base(tokens)
    if _is_yoke_payload_path_segment(command_base, tokens):
        return []
    is_search = command_base in _SEARCH_COMMANDS
    sed_script_index = _sed_script_positional_index(command_base, tokens)

    out: List[str] = []
    seen_command_name = False
    positional_index = -1

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok in REDIRECT_OPERATORS:
            if i + 1 < n:
                target = path_target_from_token(tokens[i + 1], bindings)
                if target is not None:
                    out.append(target)
            i += 2
            continue
        if not is_search:
            if tok in FLAG_BINARY and i + 1 < n:
                value = tokens[i + 1]
                if value and not value.startswith("-"):
                    out.append(value)
                i += 2
                continue
            matched_equals = False
            for prefix in FLAG_EQUALS_PREFIXES:
                if tok.startswith(prefix):
                    value = tok[len(prefix):]
                    if value:
                        out.append(value)
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
            if not is_search and positional_index != sed_script_index:
                target = path_target_from_token(tok, bindings)
                if target is not None:
                    out.append(target)
        i += 1

    return out


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
    "extract_command_targets",
    "extract_heredoc_sections",
    "strip_heredoc_body_lines",
    "strip_env_prefixes",
    "strip_heredoc_syntax",
]
