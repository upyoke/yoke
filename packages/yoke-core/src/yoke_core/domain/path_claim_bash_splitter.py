"""Quote-aware pipeline splitter for the path-claim Bash guard.

Extracted from :mod:`yoke_core.domain.path_claim_bash_parser` so the
parser stays under the 350-line cap and so quote-aware splitting has a
single tested owner. The parser still owns segment classification,
verb/target extraction, ``ambiguous`` synthesis, and heredoc/eval
fail-closed handling — this module only owns the boundary split.

The original splitter ignored quoting. That misclassified
``db_router query -separator "|" "..."`` as a real shell pipeline and
caused the path-claim Bash guard to deny it as ambiguous. This splitter honours single quotes,
double quotes, and backslash escapes — the splittable forms a real
shell would actually treat as pipeline boundaries.

Heredocs (``<<EOF``, ``<<-EOF``, ``<<'EOF'``, ``<<"EOF"``) remain
intentionally fail-closed at the parser level via the
``_FAIL_CLOSED_PREFIXES`` sweep and the heredoc detector. This
splitter does NOT try to absorb a heredoc body into a single segment;
the parser refuses heredoc-bearing commands wholesale before reaching
this layer.
"""

from __future__ import annotations

from typing import List


def split_pipeline(command: str) -> List[str]:
    """Split a Bash command on quote-aware ``;`` / ``&&`` / ``||`` / ``|`` / ``\\n``.

    Operators inside single-quoted, double-quoted, or backslash-escaped
    spans are treated as literal characters and do NOT split. Empty
    segments are dropped. Whitespace around segment boundaries is
    stripped.

    Newlines outside of quotes act as statement separators (shell
    treats unquoted ``\\n`` like ``;``) — BUT only when the command
    contains no unquoted heredoc (``<<MARKER``). With a heredoc
    present, the body is intentionally opaque to this splitter; the
    parser handles heredocs via the fail-closed sweep. Splitting on
    newline inside a heredoc body would parse prose lines as shell
    statements, which is a false-positive class we explicitly avoid.

    Without the newline split, a multi-line command body merges into
    a single segment whose first verb absorbs every positional token
    from every line — exactly the failure mode that misclassified
    ``tee /tmp/x\\n_rc=${PIPESTATUS[0]}\\n``... as a tee with extra
    positional targets.

    Examples:

    - ``"a | b"`` -> ``["a", "b"]`` (real pipeline)
    - ``'cmd -separator "|"'`` -> ``["cmd -separator \"|\""]`` (quoted ``|`` is literal)
    - ``"a && b ; c"`` -> ``["a", "b", "c"]``
    - ``"echo \\| not-a-pipe"`` -> ``["echo \\| not-a-pipe"]`` (escaped ``|`` is literal)
    - ``"a\\nb"`` -> ``["a", "b"]`` (newline is a statement separator)
    - ``"cat <<EOF\\nbody\\nEOF"`` -> single segment (heredoc body is opaque)
    """
    split_on_newline = not has_unquoted_heredoc(command)
    out: List[str] = []
    buf: List[str] = []
    i = 0
    in_single = False
    in_double = False
    n = len(command)
    while i < n:
        ch = command[i]
        # Backslash escape (outside single quotes).
        if ch == "\\" and not in_single and i + 1 < n:
            buf.append(ch)
            buf.append(command[i + 1])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if in_single or in_double:
            buf.append(ch)
            i += 1
            continue
        # Two-character operators: ``&&`` / ``||`` / ``;;``.
        if (
            ch in ";|&"
            and i + 1 < n
            and command[i + 1] == ch
        ):
            seg = "".join(buf).strip()
            if seg:
                out.append(seg)
            buf = []
            i += 2
            continue
        # Single-character pipeline operators: ``;`` / ``|`` / ``\n``.
        # Newline split is gated on absence of heredoc so heredoc body
        # lines stay opaque (see docstring).
        if ch in (";", "|") or (ch == "\n" and split_on_newline):
            seg = "".join(buf).strip()
            if seg:
                out.append(seg)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


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
        i += 1
    return False


__all__ = ["has_unquoted_heredoc", "split_pipeline"]
