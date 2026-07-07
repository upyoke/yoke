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


def _outer_substitutions(segment: str) -> List[Tuple[int, str]]:
    """Return ``(start_index, body)`` for outer ``$(...)`` substitutions.

    Quote-aware: ``$(...)`` inside single quotes is skipped. Inside
    double quotes ``$(...)`` is still parsed by shell semantics so the
    body is captured. Nested parens inside the body are balanced.
    """
    out: List[Tuple[int, str]] = []
    n = len(segment)
    i = 0
    in_single = False
    in_double = False
    while i < n:
        ch = segment[i]
        if ch == "\\" and not in_single and i + 1 < n:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if in_single:
            i += 1
            continue
        if ch == "$" and i + 1 < n and segment[i + 1] == "(":
            depth = 1
            j = i + 2
            body_start = j
            while j < n and depth > 0:
                cj = segment[j]
                if cj == "\\" and j + 1 < n:
                    j += 2
                    continue
                if cj == "(":
                    depth += 1
                elif cj == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if depth == 0:
                out.append((i, segment[body_start:j]))
                i = j + 1
                continue
            break
        i += 1
    return out


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
    while j >= 0 and before[j] in (' ', '\t', '\n', '"', "'"):
        j -= 1
    end = j + 1
    # Walk backward to the previous whitespace boundary to capture the
    # preceding token.
    while j >= 0 and before[j] not in (' ', '\t', '\n'):
        j -= 1
    last_token = before[j + 1:end].strip("'\"")
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


__all__ = ["classify_substitution_bodies"]
