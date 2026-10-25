"""Quote- and substitution-aware statement splitter shared by every Bash hook guard.

Quoted and backslash-escaped operators are literal: ``db_router query
-separator "|" "..."`` is one statement, not a pipeline. Operators inside a
command substitution (``$(...)``, backticks) or a process substitution
(``<(...)``, ``>(...)``) belong to that inner command, so ``x=$(a | b)`` is
one statement too. ``shell_parse`` builds the shared per-hook parse on this
split; the path-claim parser and the quoted-substitution lint use it as well.
"""

from __future__ import annotations

from typing import List, Tuple

_SUBSTITUTION_OPENERS = ("$(", "<(", ">(")


def has_unquoted_heredoc(segment: str) -> bool:
    """Return True iff ``<<`` appears outside single/double quotes / escapes.

    Real heredocs (``cat <<EOF``) still fail closed at the parser level;
    quoted search literals like ``grep -n "python3 - <<" file`` are
    allowed because the ``<<`` is shell-inert text. Bash ``<<<``
    here-strings still fail closed for safety.
    """
    n = len(segment)
    i = 0
    in_single = False
    in_double = False
    while i < n - 1:
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
        if not in_single and not in_double and ch == "<" and segment[i + 1] == "<":
            return True
        if (
            not in_single
            and not in_double
            and ch == "#"
            and (i == 0 or segment[i - 1].isspace())
        ):
            end = segment.find("\n", i)
            i = n if end < 0 else end
            continue
        i += 1
    return False


def pipeline_spans(
    command: str, *, shell_comments: bool = False, split_background: bool = False
) -> List[List[Tuple[int, str]]]:
    """Return each statement as its ``|`` stages, each with its start offset.

    Statement boundaries (top level only): ``;`` / ``&&`` / ``||`` / newline,
    and ``&`` when ``split_background`` is set (never the ``&`` of ``>&`` or
    ``&>``). Stage boundaries within a statement: ``|``. Text inside quotes,
    after a backslash, or inside ``$(...)``, backticks, ``<(...)`` or
    ``>(...)`` never splits. Each stage is stripped; its offset points at its
    first non-space character in ``command``. Empty stages are dropped.

    Newlines split statements only when the command has no unquoted heredoc
    (``<<MARKER``) or ``split_background`` is set: a heredoc body stays
    opaque so its prose lines are never read as statements. With
    ``shell_comments``, an unquoted ``#`` at a word start runs to the end of
    its line and is kept in the stage text.
    """
    split_on_newline = split_background or not has_unquoted_heredoc(command)
    groups: List[List[Tuple[int, str]]] = []
    stages: List[Tuple[int, str]] = []
    # Closers still owed, innermost last: ``'``, ``"``, ``)`` or a backtick.
    nesting: List[str] = []
    start = 0
    i = 0
    n = len(command)

    def flush_stage(end: int) -> None:
        text = command[start:end]
        stripped = text.strip()
        if stripped:
            stages.append((start + len(text) - len(text.lstrip()), stripped))

    def flush_group(end: int) -> None:
        flush_stage(end)
        if stages:
            groups.append(list(stages))
            stages.clear()

    while i < n:
        ch = command[i]
        inner = nesting[-1] if nesting else ""
        if inner == "'":
            if ch == "'":
                nesting.pop()
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if inner == '"':
            if ch == '"':
                nesting.pop()
            elif ch == "`":
                nesting.append("`")
            elif command.startswith("$(", i):
                nesting.append(")")
                i += 1
            i += 1
            continue
        if ch in "'\"":
            nesting.append(ch)
            i += 1
            continue
        if ch == "`":
            if inner == "`":
                nesting.pop()
            else:
                nesting.append("`")
            i += 1
            continue
        if command.startswith(_SUBSTITUTION_OPENERS, i):
            nesting.append(")")
            i += 2
            continue
        if nesting:
            if ch == "(":
                nesting.append(")")
            elif ch == ")" and inner == ")":
                nesting.pop()
            i += 1
            continue
        if shell_comments and ch == "#" and (i == start or command[i - 1].isspace()):
            end = command.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch in ";|&" and i + 1 < n and command[i + 1] == ch:
            flush_group(i)
            i += 2
            start = i
            continue
        background = (
            split_background
            and ch == "&"
            and (i == 0 or command[i - 1] != ">")
            and (i + 1 == n or command[i + 1] != ">")
        )
        if ch == "|":
            flush_stage(i)
        elif ch == ";" or background or (ch == "\n" and split_on_newline):
            flush_group(i)
        else:
            i += 1
            continue
        i += 1
        start = i
    flush_group(n)
    return groups


def iter_pipeline_groups(
    command: str, *, shell_comments: bool = False, split_background: bool = False
) -> List[List[str]]:
    """Return each statement as its ``|`` stages (see :func:`pipeline_spans`).

    - ``"pytest -q | head -5 && echo done"`` -> ``[["pytest -q", "head -5"], ["echo done"]]``
    - ``"cmd --evidence 'a | b'"`` -> one stage (quoted ``|`` is literal)
    - ``"x=$(git log | head -1)"`` -> one stage (the ``|`` is inside ``$(...)``)
    - ``"cat <<EOF\\nbody\\nEOF"`` -> one stage (heredoc body is opaque)
    """
    return [
        [text for _, text in group]
        for group in pipeline_spans(
            command, shell_comments=shell_comments, split_background=split_background
        )
    ]


def split_pipeline(
    command: str, *, split_background: bool = False, shell_comments: bool = False
) -> List[str]:
    """Return every pipeline stage of every statement, in order."""
    return [
        stage
        for group in iter_pipeline_groups(
            command, shell_comments=shell_comments, split_background=split_background
        )
        for stage in group
    ]


__all__ = ["has_unquoted_heredoc", "iter_pipeline_groups", "pipeline_spans", "split_pipeline"]
