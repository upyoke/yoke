"""Heredoc-aware redirect-target extractor for the path-claim Bash parser.

Sibling of :mod:`path_claim_bash_parser`. Owns the redirect-target
resolution for compound heredoc / command-substitution shapes so the
parent module stays under the 350-line authored-file cap.

The single public function :func:`extract_heredoc_redirect_target`
inspects a segment that contains an unquoted ``<<`` heredoc opener
and returns the first ``>`` / ``>>`` redirect target path that
appears BEFORE the heredoc body, or ``None`` when no redirect target
is parseable. This is the S3 / Class B sub-case fix: heredocs with a
clean redirect (``cat > /tmp/file <<'EOF' ... EOF``,
``cat > <claim-covered-path> <<'EOF' ... EOF``) emit a real
``Mutation(verb="redirect", target_path=...)`` so the existing
path-coverage check handles free-path vs claim-covered vs denied
uniformly.

Pure function, no I/O. Quote-aware so escaped / quoted ``>`` is not
mistaken for a redirect operator.
"""

from __future__ import annotations

from typing import Optional


def extract_heredoc_redirect_target(segment: str) -> Optional[str]:
    """Return the first ``>``/``>>`` redirect target on the segment's first line.

    The walk is quote-aware: single quotes, double quotes, and
    backslash escapes are honored. Returns the token immediately
    following the redirect operator after stripping surrounding
    whitespace. ``None`` means no redirect is parseable on the
    segment's command line (the heredoc body following ``<<MARKER``
    on a subsequent line is intentionally skipped — its contents
    are not parsed for redirects).

    For commit-message-only heredocs (``git commit -m
    "$(cat <<'EOF' ... EOF)"``) the operator appears INSIDE a
    quoted span so the walk never matches and the caller falls
    through to allow. For ``cat <<EOF > out.txt\\nbody\\nEOF`` the
    ``> out.txt`` is on the same command line as the heredoc opener
    so the walk extracts ``out.txt``.
    """
    if not segment:
        return None
    # Only inspect the first line of the segment; subsequent lines
    # are the heredoc body and never carry a real command-line
    # redirect operator.
    first_line, _, _ = segment.partition("\n")
    n = len(first_line)
    i = 0
    in_single = False
    in_double = False
    while i < n:
        ch = first_line[i]
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
        if in_single or in_double:
            i += 1
            continue
        # Heredoc opener: skip past the marker token; the redirect
        # may still appear after it on the same command line.
        if ch == "<" and i + 1 < n and first_line[i + 1] == "<":
            i += 2
            # Skip optional ``-`` (here-doc-dash) and quote chars,
            # then the marker word itself.
            if i < n and first_line[i] == "-":
                i += 1
            while i < n and first_line[i] in ("'", '"'):
                i += 1
            while i < n and (first_line[i].isalnum() or first_line[i] == "_"):
                i += 1
            while i < n and first_line[i] in ("'", '"'):
                i += 1
            continue
        # Redirect operator. Consume the token that follows.
        if ch == ">":
            op_len = 2 if i + 1 < n and first_line[i + 1] == ">" else 1
            j = i + op_len
            while j < n and first_line[j] in (" ", "\t"):
                j += 1
            target_start = j
            while j < n and first_line[j] not in (
                " ", "\t", "<", ">", "|", ";", "&",
            ):
                j += 1
            target = first_line[target_start:j].strip()
            target = _strip_paired_quotes(target)
            if target:
                return target
            i = j
            continue
        i += 1
    return None


def _strip_paired_quotes(target: str) -> str:
    """Strip surrounding matched single or double quotes from ``target``.

    The non-heredoc redirect path resolves quotes via ``shlex.split``;
    the heredoc-aware walker reads characters directly and so retains
    the surrounding quote chars. Strip them here so downstream
    consumers (``is_temp_file_var_ref`` for mktemp-bound vars, the
    free-path target check) see the same bare token shape that the
    shlex path produces.
    """
    if len(target) >= 2 and target[0] == target[-1] and target[0] in ('"', "'"):
        return target[1:-1]
    return target


__all__ = ["extract_heredoc_redirect_target"]
