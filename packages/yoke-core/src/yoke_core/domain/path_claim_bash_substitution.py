"""``$(...)`` substitution body classifier for the path-claim Bash parser.

Sibling helper for :mod:`path_claim_bash_parser`. The canonical commit
form taught in ``AGENTS.md`` is ``git commit -m "$(cat <<'EOF' ... EOF)"``
— a literal-message construct that carries no path-mutation signal.
The narrow Bug 4 whitelist allows that exact shape (heredoc literal
body feeding a text-flag consumer) while denying any other ``$(...)``
substitution whose body leads with a mutating verb.

Quote-aware: ``$(...)`` inside single quotes is ignored. Inside double
quotes ``$(...)`` is still active per shell semantics and is scanned.

Pure function, no I/O, no DB access.
"""

from __future__ import annotations

import re
from typing import List, Tuple


_MUTATE_VERBS = frozenset({"rm", "mv", "cp", "tee", "truncate"})
_TEXT_FLAG_CONSUMERS = frozenset({"-m", "--message", "--body", "-F"})

_CAT_HEREDOC_LITERAL_RE = re.compile(
    r"""^\s*cat\s+<<-?\s*['"]?(?P<marker>\w+)['"]?\s*\n.*?\n\s*"""
    r"""(?P=marker)\s*$""",
    re.DOTALL,
)

_GIT_MUTATE_SUBCMDS = frozenset({"rm", "restore", "checkout"})


def classify_substitution_bodies(segment: str) -> str:
    """Return ``"ok"`` or ``"ambiguous"`` for ``$(...)`` bodies in ``segment``.

    ``ok`` means every outer-level ``$(...)`` is structurally benign:

    * ``mktemp [args]`` — variable-binding subshell, target tracked
      separately by :mod:`path_claim_bash_temp_vars`.
    * ``cat <<'EOF' ... EOF`` heredoc literal feeding a text-flag
      consumer (``-m`` / ``--message`` / ``--body`` / ``-F``).
    * Plain read commands (date, hostname, pwd, etc.).

    ``ambiguous`` means at least one ``$(...)`` body leads with a
    mutating verb (``rm``, ``mv``, ``cp``, ``tee``, ``truncate``,
    ``git rm`` / ``git restore`` / ``git checkout``) outside the
    whitelisted shape. The caller emits a single
    ``Mutation(verb="ambiguous", ...)`` so the path-claim guard fails
    closed.
    """
    for offset, body in _outer_substitutions(segment):
        stripped = body.strip()
        if not stripped:
            continue
        if _is_mktemp_body(stripped):
            continue
        if _is_cat_heredoc_literal(stripped) and _consumer_is_text_flag(
            segment, offset
        ):
            continue
        first_token = stripped.split(maxsplit=1)[0]
        if first_token in _MUTATE_VERBS:
            return "ambiguous"
        if first_token == "git" and _git_subcmd_is_mutating(stripped):
            return "ambiguous"
    return "ok"


def _substitution_end(text: str, start: int, *, tick: bool = False) -> int | None:
    """Find the closing delimiter, respecting body quotes and nested sources."""
    depth = 1
    single = double = False
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\" and not single:
            i += 2
            continue
        if tick:
            if ch == chr(96):
                return i
        elif not single and text.startswith("$(", i):
            end = _substitution_end(text, i + 2)
            if end is None:
                return None
            i = end + 1
            continue
        elif not single and ch == chr(96):
            end = _substitution_end(text, i + 1, tick=True)
            if end is None:
                return None
            i = end + 1
            continue
        elif ch == "'" and not double:
            single = not single
        elif ch == '"' and not single:
            double = not double
        elif not single and not double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def _substitution_spans(
    text: str,
    *,
    literal_quotes: bool = False,
) -> List[Tuple[int, int, str, str]]:
    """Extract executable outer spans once for all substitution consumers."""
    spans: List[Tuple[int, int, str, str]] = []
    i = 0
    single = double = False
    while i < len(text):
        ch = text[i]
        if ch == "\\" and not single:
            i += 2
            continue
        if not literal_quotes:
            if ch == "'" and not double:
                single = not single
            elif ch == '"' and not single:
                double = not double
            elif (
                ch == "#"
                and not single
                and not double
                and (i == 0 or text[i - 1].isspace() or text[i - 1] in ";|&(")
            ):
                end = text.find("\n", i)
                i = len(text) if end < 0 else end
                continue
        kind = ""
        if not single:
            if text.startswith("$(", i):
                kind = "command"
            elif ch == chr(96):
                kind = "tick"
            elif not double and text[i : i + 2] in ("<(", ">("):
                kind = "process"
        if kind:
            body_start = i + (1 if kind == "tick" else 2)
            end = _substitution_end(text, body_start, tick=kind == "tick")
            if end is None:
                # Retain malformed syntax in the outer command for a named
                # unresolved-syntax verdict instead of granting an exemption.
                break
            spans.append((i, end + 1, text[body_start:end], kind))
            i = end + 1
            continue
        i += 1
    return spans


def _outer_substitutions(segment: str) -> List[Tuple[int, str]]:
    """Return command substitution bodies for the path mutation classifier."""
    return [
        (start, body)
        for start, _end, body, kind in _substitution_spans(segment)
        if kind == "command"
    ]


def executable_substitutions(
    command: str,
    *,
    literal_quotes: bool = False,
) -> Tuple[str, List[str]]:
    """Mask expansions in outer argv and return the shell sources they run.

    Single quotes and escapes are inert; double quotes still expand.
    Unquoted heredoc bodies have literal quote characters, which callers name
    explicitly. This is source extraction, never evaluation or execution.
    """
    parts: List[str] = []
    bodies: List[str] = []
    previous = 0
    for start, end, body, _kind in _substitution_spans(
        command,
        literal_quotes=literal_quotes,
    ):
        parts.extend((command[previous:start], "__shell_expansion__"))
        bodies.append(body)
        previous = end
    parts.append(command[previous:])
    return "".join(parts), bodies


def _is_mktemp_body(body: str) -> bool:
    stripped = body.strip()
    if stripped == "mktemp":
        return True
    return stripped.startswith("mktemp ") or stripped.startswith("mktemp\t")


def _is_cat_heredoc_literal(body: str) -> bool:
    return _CAT_HEREDOC_LITERAL_RE.match(body) is not None


def _consumer_is_text_flag(segment: str, substitution_start: int) -> bool:
    """True iff the substitution at ``substitution_start`` is preceded by
    one of the text-flag consumers (``-m`` / ``--message`` / ``--body``
    / ``-F``) — with optional surrounding double-quote and whitespace.
    """
    before = segment[:substitution_start]
    # Trim trailing whitespace and any single opening quote.
    j = len(before) - 1
    while j >= 0 and before[j] in (" ", "\t", "\n", '"', "'"):
        j -= 1
    end = j + 1
    # Walk backward to the previous whitespace boundary to capture the
    # preceding token.
    while j >= 0 and before[j] not in (" ", "\t", "\n"):
        j -= 1
    last_token = before[j + 1 : end].strip("'\"")
    if last_token in _TEXT_FLAG_CONSUMERS:
        return True
    # ``--message=...`` shape: token has ``=`` and base name is in the set.
    if "=" in last_token:
        base = last_token.split("=", 1)[0]
        if base in _TEXT_FLAG_CONSUMERS:
            return True
    return False


def _git_subcmd_is_mutating(body: str) -> bool:
    """True iff ``body`` is ``git [-C dir]* <mutate-subcmd> ...``."""
    tokens = body.split()
    i = 1  # skip ``git``
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-C", "-c") and i + 1 < len(tokens):
            i += 2
            continue
        if tok.startswith(("--git-dir=", "--work-tree=")):
            i += 1
            continue
        return tok in _GIT_MUTATE_SUBCMDS
    return False


__all__ = ["classify_substitution_bodies", "executable_substitutions"]
