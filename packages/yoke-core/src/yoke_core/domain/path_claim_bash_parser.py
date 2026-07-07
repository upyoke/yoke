"""Bash file-mutation parser — pure function, fail-closed on ambiguity.

Given a Bash command string, return a list of ``(verb, target_path)``
tuples covering file mutations. Mutating verbs: ``rm``, ``mv``, ``cp``,
``tee``, ``truncate``; ``>``/``>>`` redirects; ``git rm`` /
``git restore`` / ``git checkout --``; ``find ... -delete``. Read-only
inspection commands return no targets so path claims do not blind
agents during orientation. Heredocs with a clean ``>`` redirect to a
free path or claim-covered worktree path emit a real ``Mutation``;
heredocs with no redirect and no leading write verb fall through with
zero mutations (S3 / Class B). Opaque shells (``eval``, ``bash -c``,
heredoc + write verb without parseable target) emit one synthetic
``("ambiguous", "<command-snippet>")`` so the guard fails closed.
The ``# lint:no-worktree-path-check`` suppression token short-circuits
with a single ``("suppressed", token)`` tuple. Public surface:
:class:`Mutation`, :func:`extract_mutations`.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import List

from yoke_core.domain.path_claim_bash_substitution import (
    classify_substitution_bodies,
)
from yoke_core.domain.path_claim_bash_temp_vars import (
    is_temp_file_var_ref,
    temp_file_vars,
)


SUPPRESSION_TOKEN = "# lint:no-worktree-path-check"


# Mutating verbs that take positional file arguments (last positional is
# the destination for cp/mv; rm/tee accept multiple).
_MUTATE_TARGET_VERBS = frozenset({
    "rm", "mv", "cp", "tee", "truncate",
})

# git subcommands that modify specific files. Read-only git inspection
# (``status``, ``log``, ``show``, ``diff``) intentionally emits no targets.
_GIT_MUTATE_SUBCMDS = frozenset({"rm", "restore", "checkout"})

# Idioms we MUST fail-closed on (ambiguous to a token-level parser).
_FAIL_CLOSED_PREFIXES = ("eval ", "eval\t", "exec ", "exec\t")
# ``bash -c`` AND ``sh -c`` both run an opaque inline body; classify both
# as ambiguous so a ``grep ... | sh -c 'rm $1'`` shape cannot smuggle a
# mutation past the parser.
_FAIL_CLOSED_C_RES = ("bash -c", "sh -c")
_FAIL_CLOSED_BASH_C_RE = "bash -c"
# Heredoc detection lives in :func:`_has_unquoted_heredoc` so quoted
# search literals like ``grep -n "python3 - <<" file`` no longer
# misclassify as heredoc syntax.

# Tokens that look like flag args; everything else is a candidate path.
def _is_flag(token: str) -> bool:
    return token.startswith("-") and token != "-"


def _is_tmp_path(path: str) -> bool:
    return path.startswith("/tmp/") or path == "/tmp"


def _strip_redirect_targets(tokens: List[str]) -> List[str]:
    """Remove ``>``/``>>`` and consume redirect-target tokens.

    Returns ``tokens`` with redirect tokens stripped. Captured target
    paths are not returned here — the caller (``extract_mutations``)
    walks the original token stream to record them as ``redirect``
    verbs.
    """
    out: List[str] = []
    skip = False
    for tok in tokens:
        if skip:
            skip = False
            continue
        if tok in (">", ">>"):
            skip = True
            continue
        out.append(tok)
    return out


@dataclass(frozen=True)
class Mutation:
    """One file-mutation extracted from a Bash command."""

    verb: str
    target_path: str


from yoke_core.domain.path_claim_bash_splitter import (
    has_unquoted_heredoc as _has_unquoted_heredoc,
    split_pipeline as _split_pipeline,
)


def _extract_redirect_paths(segment: str) -> List[Mutation]:
    """Pull every ``>``/``>>`` target path from a segment."""
    out: List[Mutation] = []
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return [Mutation(verb="ambiguous", target_path=segment[:80])]
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in (">", ">>") and i + 1 < len(tokens):
            target = tokens[i + 1]
            if target and not _is_tmp_path(target):
                out.append(Mutation(verb="redirect", target_path=target))
            i += 2
            continue
        i += 1
    return out


def _extract_verb_paths(verb: str, args: List[str]) -> List[Mutation]:
    """Pull positional file paths from a verb's arg list."""
    # Keep simple positionals (drop --flag and --flag=value)
    pos: List[str] = []
    for a in args:
        if _is_flag(a):
            continue
        pos.append(a)
    out: List[Mutation] = []
    if verb in ("cp", "mv") and len(pos) >= 1:
        # Destination is the last positional.
        dest = pos[-1]
        if dest and not _is_tmp_path(dest):
            out.append(Mutation(verb=verb, target_path=dest))
    elif verb in _MUTATE_TARGET_VERBS:
        for p in pos:
            if not p:
                continue
            if _is_tmp_path(p):
                continue
            out.append(Mutation(verb=verb, target_path=p))
    return out


def _extract_git_paths(args: List[str]) -> List[Mutation]:
    """Pull paths from ``git rm``/``git restore``/``git checkout --``.

    Read-only git inspection is an explicit allow case, including
    path-specific forms such as ``git diff -- path``.
    """
    args = _strip_git_global_options(args)
    if not args:
        return []
    sub = args[0]
    if sub not in _GIT_MUTATE_SUBCMDS:
        return []

    # Find positional paths after the optional ``--`` separator.
    rest = args[1:]
    if "--" in rest:
        idx = rest.index("--")
        paths = [p for p in rest[idx + 1:] if p and not _is_flag(p)]
    else:
        paths = [p for p in rest if p and not _is_flag(p)]

    out: List[Mutation] = []
    verb = f"git {sub}"
    for p in paths:
        if _is_tmp_path(p):
            continue
        out.append(Mutation(verb=verb, target_path=p))
    return out


def _strip_git_global_options(args: List[str]) -> List[str]:
    """Drop common git global options so the subcommand is first."""
    i = 0
    while i < len(args):
        token = args[i]
        if token in ("-C", "-c") and i + 1 < len(args):
            i += 2
            continue
        if token.startswith(("--git-dir=", "--work-tree=")):
            i += 1
            continue
        break
    return args[i:]


def _extract_find_paths(args: List[str]) -> List[Mutation]:
    """Pull the search root from ``find <root> ... -delete``."""
    if "-delete" not in args:
        return []
    # First non-flag arg is the search root (defaults to '.' if absent).
    root = "."
    for a in args:
        if not _is_flag(a) and not a.startswith("-"):
            root = a
            break
    if _is_tmp_path(root):
        return []
    return [Mutation(verb="find -delete", target_path=root)]


def _classify_segment(segment: str) -> List[Mutation]:
    """Classify a single pipeline segment.

    Returns ``[Mutation("ambiguous", ...)]`` when the segment cannot be
    statically parsed. Returns ``[]`` for explicit allow cases.
    Compound shapes with a clean ``>`` / ``>>`` redirect emit a real
    ``Mutation("redirect", ...)`` so the consuming guard's target
    coverage handles ``/tmp`` / claim-covered / repo-tree-without-claim
    uniformly (S3 / Class B sub-case).
    """
    stripped = segment.strip()
    if not stripped:
        return []

    # Fail-closed prefixes.
    if any(stripped.startswith(p) for p in _FAIL_CLOSED_PREFIXES):
        return [Mutation(verb="ambiguous", target_path=stripped[:80])]

    if any(shell_c in stripped for shell_c in _FAIL_CLOSED_C_RES):
        return [Mutation(verb="ambiguous", target_path=stripped[:80])]

    # ``$(...)`` substitution body classification — canonical
    # ``$(cat <<'EOF' ... EOF)`` feeding a text-flag consumer is benign;
    # any other body with a mutating verb head is ambiguous.
    if classify_substitution_bodies(stripped) == "ambiguous":
        return [Mutation(verb="ambiguous", target_path=stripped[:80])]

    # Here-doc — fall through to redirect / verb extraction. A clean
    # ``>`` redirect emits a real ``Mutation``; zero-write-verb /
    # zero-redirect heredocs (``git commit -m "$(cat <<EOF ...)"``)
    # fall through with no mutations; heredocs with embedded write
    # verbs we cannot parse statically stay ambiguous.
    has_heredoc = _has_unquoted_heredoc(stripped)
    redirect_muts = _extract_heredoc_aware_redirects(stripped, has_heredoc)
    if has_heredoc and redirect_muts == "ambiguous":
        return [Mutation(verb="ambiguous", target_path=stripped[:80])]

    # Single tokenize pass — shlex keeps quoted arg bodies opaque so
    # regex patterns inside ``grep`` quotes do not classify as
    # ambiguous shell tokens (Bug 6).
    tokens = _safe_tokenize(stripped)
    if not tokens:
        if has_heredoc:
            return list(redirect_muts)
        first_word = stripped.split(maxsplit=1)[0] if stripped else ""
        if first_word in _MUTATE_TARGET_VERBS or first_word == "git":
            return list(redirect_muts) + [
                Mutation(verb="ambiguous", target_path=stripped[:80])
            ]
        return list(redirect_muts)

    sanitized_tokens = _strip_redirect_targets(tokens)
    if not sanitized_tokens:
        return list(redirect_muts)

    verb = sanitized_tokens[0]
    args = sanitized_tokens[1:]

    out: List[Mutation] = list(redirect_muts)
    if verb == "git":
        out.extend(_extract_git_paths(args))
        return out
    if verb == "find":
        out.extend(_extract_find_paths(args))
        return out
    if verb in _MUTATE_TARGET_VERBS:
        out.extend(_extract_verb_paths(verb, args))
    return out


def _extract_heredoc_aware_redirects(
    stripped: str, has_heredoc: bool,
):
    """Extract redirects for a segment that may have a heredoc.

    Returns a list of :class:`Mutation` redirect entries on success.
    Returns the sentinel ``"ambiguous"`` when the segment has a heredoc
    body that the redirect-target extractor cannot parse and the
    segment leads with a mutating write verb.
    """
    if not has_heredoc:
        return _extract_redirect_paths(stripped)
    try:
        from yoke_core.domain.path_claim_bash_parser_redirect import (
            extract_heredoc_redirect_target,
        )
        target = extract_heredoc_redirect_target(stripped)
    except Exception:
        target = None
    if target is None:
        first_token = stripped.split(maxsplit=1)[0] if stripped else ""
        if first_token in _MUTATE_TARGET_VERBS or first_token == "git":
            return "ambiguous"
        return []
    if _is_tmp_path(target):
        return []
    return [Mutation(verb="redirect", target_path=target)]


def _safe_tokenize(segment: str) -> List[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return []


def extract_mutations(command: str) -> List[Mutation]:
    """Extract ``(verb, target_path)`` tuples from a Bash command.

    Returns a (possibly empty) list. ``ambiguous`` entries indicate the
    parser fell closed on a chunk — the consuming guard MUST treat them
    as deny. ``suppressed`` entries indicate the operator added the
    ``# lint:no-worktree-path-check`` token; the guard records audit
    evidence and allows.
    """
    if not command or not isinstance(command, str):
        return []

    if SUPPRESSION_TOKEN in command:
        return [Mutation(verb="suppressed", target_path=SUPPRESSION_TOKEN)]

    tmp_vars = temp_file_vars(command)
    out: List[Mutation] = []
    for segment in _split_pipeline(command):
        out.extend(_classify_segment(segment))
    filtered = [
        mut for mut in out
        if not is_temp_file_var_ref(mut.target_path, tmp_vars)
    ]
    # Planning-phase carve-out: drop session-scratch redirects when the
    # session's item is pre-implementation. Local import avoids a
    # bash_parser <-> planning_phase circular at module load.
    from yoke_core.domain.path_claim_bash_parser_planning_phase import (
        drop_planning_scratch_mutations,
    )
    return drop_planning_scratch_mutations(filtered)


__all__ = [
    "Mutation",
    "SUPPRESSION_TOKEN",
    "extract_mutations",
]
