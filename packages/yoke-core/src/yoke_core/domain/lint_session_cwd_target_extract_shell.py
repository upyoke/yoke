"""Shell-command target extraction for the session-cwd lint."""

from __future__ import annotations

import re
import shlex
from typing import List, Optional, Tuple


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

_POSITIONAL_REGEX_METACHARS = re.compile(r"[?*{]")
_POSITIONAL_COLON = re.compile(r".+:.+")
_POSITIONAL_SED_ANCHOR_PREFIX = "/^"
_POSITIONAL_URL_VERSION = re.compile(r"^/v\d+/")


def _is_path_like_positional(token: str) -> bool:
    """Return True only when ``token`` looks like a real absolute path."""
    if not token or not token.startswith("/"):
        return False
    # Bare filesystem root: never a write target an agent specifies. A lone
    # ``/`` reaching here is almost always a tokenized shell / Python ``/``
    # operator (for example ``project_tree / "templates"`` surfacing from an
    # apply_patch / Write body), not a real path.
    if token == "/":
        return False
    # Unexpanded shell variable (``$_sock``, ``/tmp/$VAR/x``): the lint
    # inspects the command string statically and cannot resolve the
    # variable, so it cannot validate the real path. Skip rather than deny on
    # the literal ``$``-bearing string.
    if "$" in token:
        return False
    if token.startswith(_POSITIONAL_SED_ANCHOR_PREFIX):
        return False
    if _POSITIONAL_URL_VERSION.match(token):
        return False
    if _POSITIONAL_REGEX_METACHARS.search(token):
        return False
    if _POSITIONAL_COLON.match(token):
        return False
    return True


def extract_command_targets(command: str) -> List[str]:
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
    """
    sanitized = _strip_heredoc_body_lines(command)
    tokens = _safe_split(sanitized)
    if not tokens:
        return []

    out: List[str] = []
    for segment in _split_command_segments(tokens):
        out.extend(_extract_segment_targets(segment))
    return out


# Shell control operators that separate one command invocation from the
# next. ``extract_command_targets`` splits on these so each segment's
# leading token is recognised as that segment's command name.
_SEGMENT_SEPARATORS = frozenset({"&&", "||", "|", "|&", ";", ";;", "&"})

_SEARCH_COMMANDS = frozenset({
    "grep", "egrep", "fgrep", "rg", "ripgrep", "ag", "ack",
})

_SED_SCRIPT_FLAGS = ("-e", "-f", "--expression", "--file")

_REDIRECT_OPERATORS = frozenset({
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


def _extract_segment_targets(tokens: List[str]) -> List[str]:
    """Extract target paths from a single command segment."""
    tokens = _strip_env_prefixes(tokens)
    if not tokens:
        return []

    command_base = _segment_command_base(tokens)
    is_search = command_base in _SEARCH_COMMANDS
    sed_script_index = _sed_script_positional_index(command_base, tokens)

    out: List[str] = []
    seen_command_name = False
    positional_index = -1

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok in _REDIRECT_OPERATORS:
            if i + 1 < n and _is_path_like_positional(tokens[i + 1]):
                out.append(tokens[i + 1])
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
            if (
                not is_search
                and positional_index != sed_script_index
                and _is_path_like_positional(tok)
            ):
                out.append(tok)
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


def _strip_heredoc_body_lines(command: str) -> str:
    """Drop heredoc body lines (and the closing-tag line) from ``command``."""
    lines = command.splitlines()
    out: List[str] = []
    pending_tag: Optional[str] = None
    dash_form: bool = False
    for line in lines:
        if pending_tag is None:
            out.append(line)
            tag, dash = _scan_heredoc_opener(line)
            if tag is not None:
                pending_tag = tag
                dash_form = dash
            continue
        candidate = line.lstrip("\t") if dash_form else line
        if candidate.strip() == pending_tag:
            pending_tag = None
            dash_form = False
    return "\n".join(out)


def _scan_heredoc_opener(line: str) -> Tuple[Optional[str], bool]:
    match = _HEREDOC_OPENER_RE.search(line)
    if match is None:
        return None, False
    tag = match.group("sq") or match.group("dq") or match.group("bare")
    return tag, bool(match.group("dash"))


def _strip_env_prefixes(tokens: List[str]) -> List[str]:
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
    "extract_command_targets",
]
