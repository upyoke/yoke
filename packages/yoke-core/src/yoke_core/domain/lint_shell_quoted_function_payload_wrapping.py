"""Clause-level wrapping classifiers for the shell-quoted-function-payload lint.

Sibling of :mod:`lint_shell_quoted_function_payload_classify`. Splits the
wrapping-shell evaluation (``is_read_wrapping``, ``is_best_effort_wrapping``,
``is_substantive_read_wrapping``) out of the classify module so both
modules stay under the 350-line authored-file cap.

The classify module owns tokenization, the help-invocation short-circuit,
adapter-registry lookups, and the ``_ScanState`` / ``_find_boundary``
primitives the wrapper splitter depends on. This module owns the
clause-level read-only / best-effort / substantive classification used
by the lint hot path to decide whether a given wrapping shape is benign
for a registered or domain-only hit.
"""

from __future__ import annotations

import re
from typing import FrozenSet, List, Optional

from yoke_core.domain.lint_session_cwd_validate import FREE_PATH_PREFIXES
from yoke_core.domain.lint_shell_quoted_function_payload_classify import (
    _ScanState,
    _find_boundary,
)


# Wrapping-clause separators. Redirect operators are NOT separators —
# they stay glued to their target inside the clause they introduce.
# Newlines split clauses identically to ``;`` at the shell level.
_CLAUSE_SEPARATORS = ("&&", "||", "|", ";", "&", "\n")

# Statement separators: a bare top-level ``\n`` ends the current
# shell statement. Anything after the newline is an independent
# statement whose wrapping does NOT bind to the registered adapter
# that triggered this scan. ``;`` is intentionally NOT a statement
# separator here — choreography patterns like ``; echo $?`` continue
# to deny on registered MUTATE adapters (see
# ``TestRegistryCoveredShellChoreography.test_mutation_choreography_still_denies``).
# The compound chain operators (``&&``, ``||``, ``|``, ``&``) also
# stay as regular clause separators.
_STATEMENT_SEPARATORS = ("\n",)

# Redirect operators consumed inside a wrapping clause. Longest match
# first so ``2>&1`` wins over ``2>`` and ``>>`` wins over ``>``.
_REDIRECT_OPS = ("2>&1", "<<<", "<<-", ">>", "2>", ">&", "<<", ">", "<")

_READ_PIPE_VERBS = frozenset({
    "head", "tail", "grep", "wc", "jq", "awk", "sed", "cut",
    "sort", "uniq", "less", "more", "nl", "cat",
})

_BENIGN_PRINT_VERBS = frozenset({"echo", "printf"})

_BEST_EFFORT_NOOP_CLAUSES = frozenset({"true", "exit 0", ":"})

_STATUS_CAPTURE_RE = re.compile(r"^[A-Za-z_]\w*=\$\?$")

_VAR_REF_RE = re.compile(
    r"""^['"]?\$\{?([A-Za-z_]\w*)\}?['"]?$"""
)


def is_read_wrapping(
    tail: str,
    mktemp_vars: FrozenSet[str] = frozenset(),
) -> bool:
    """True iff the wrapping shell after the subcommand is read-only.

    ``mktemp_vars`` carries variable names whose binding sourced from
    ``$(mktemp ...)`` earlier in the same command so a redirect target
    of ``"$var"`` is recognised as a free-path target (Bug 9).
    """
    if not tail:
        return True
    end = _find_boundary(tail)
    if end >= len(tail):
        return True
    remainder = tail[end:].lstrip()
    for clause in _split_wrapping_clauses(remainder):
        if not _clause_is_read_only(clause, mktemp_vars=mktemp_vars):
            return False
    return True


def is_substantive_read_wrapping(
    tail: str,
    mktemp_vars: FrozenSet[str] = frozenset(),
) -> bool:
    """Stricter variant of :func:`is_read_wrapping` for the
    ``_DomainOnlyHit`` branch where the lint has no registered
    function id signal.

    Requires every clause to be read-only AND at least one clause to be
    *substantive* — a read-pipe verb (``head`` / ``tail`` / ``grep`` …),
    a free-path redirect with a real target (``2>/dev/null``,
    ``>/tmp/foo``), or the mktemp-bound variable variant. Bare
    ``2>&1`` / standalone status-probe-style ``echo $?`` / lone
    ``|| true`` do not qualify on their own — they could mean "I want
    no consumer at all" which is the original terminal-soup signal the
    deny path was designed to catch.
    """
    if not tail:
        return False
    end = _find_boundary(tail)
    if end >= len(tail):
        return False
    remainder = tail[end:].lstrip()
    clauses = _split_wrapping_clauses(remainder)
    if not clauses:
        return False
    has_substantive = False
    for clause in clauses:
        if not _clause_is_read_only(clause, mktemp_vars=mktemp_vars):
            return False
        if _is_substantive_read_clause(clause, mktemp_vars=mktemp_vars):
            has_substantive = True
    return has_substantive


def is_write_output_consumer_only(
    tail: str,
    mktemp_vars: FrozenSet[str] = frozenset(),
) -> bool:
    """True iff ``tail`` is a write followed only by free-path
    redirects and pipes to stdin-consuming read verbs (no file args).

    Post-write inspection shape: ``adapter 2>&1 | tail -20``,
    ``adapter | jq -r .x``. Requires at least one pipe-to-read-verb
    clause with no path-shaped argument. Bare ``2>&1`` with no
    consumer, capture-first ``>"$_tmp" 2>&1; _rc=$?``, and
    ``| tail -f /tmp/foo`` do NOT qualify.
    """
    if not tail:
        return False
    end = _find_boundary(tail)
    if end >= len(tail):
        return False
    clauses = _split_wrapping_clauses(tail[end:].lstrip())
    has_pipe_consumer = False
    for clause in clauses:
        stripped = clause.strip()
        if any(stripped.startswith(op) for op in _REDIRECT_OPS):
            if not _clause_is_best_effort(clause, mktemp_vars=mktemp_vars):
                return False
            continue
        parts = stripped.split()
        verb = parts[0] if parts else ""
        if verb not in _READ_PIPE_VERBS:
            return False
        if any(a.startswith(("/", "./", "../")) for a in parts[1:]):
            return False
        has_pipe_consumer = True
    return has_pipe_consumer


def is_best_effort_wrapping(
    tail: str,
    mktemp_vars: FrozenSet[str] = frozenset(),
) -> bool:
    """True iff ``tail`` is a best-effort wrapper around a write.

    A best-effort wrapper composes ONLY of stdout/stderr redirects to
    free paths (``/dev/null``, ``/tmp/...``, mktemp-bound variables)
    plus a final ``|| true`` / ``|| exit 0`` short-circuit. This is
    the idiomatic shape ``/yoke do`` Step B uses for
    ``session-heartbeat`` and ``session-checkpoint`` — the mutation
    must run but its outcome must not crash the loop.

    Substantive consumer pipes (``| tee``, ``| jq -r .x``, ``| grep``)
    or arbitrary follow-on commands (``&& rm /tmp/foo``) disqualify
    the wrapper.
    """
    if not tail:
        return True
    end = _find_boundary(tail)
    if end >= len(tail):
        return True
    remainder = tail[end:].lstrip()
    saw_noop = False
    for clause in _split_wrapping_clauses(remainder):
        if not _clause_is_best_effort(clause, mktemp_vars=mktemp_vars):
            return False
        if clause.strip() in _BEST_EFFORT_NOOP_CLAUSES:
            saw_noop = True
    return saw_noop


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_wrapping_clauses(remainder: str) -> List[str]:
    """Split a wrapping tail into clauses on unquoted clause separators.

    Redirect operators do NOT separate clauses — they are the verb of
    the clause that follows them and stay glued to their target so
    :func:`_clause_is_read_only` can evaluate the operator+target
    pair. Mid-clause redirects close the prior clause and start a new
    one with the redirect as verb (Bug 1 fix).
    """
    out: List[str] = []
    buf: List[str] = []
    state = _ScanState()
    i = 0
    n = len(remainder)
    in_clause = False

    def _flush() -> None:
        text = "".join(buf).strip()
        if text:
            out.append(text)
        buf.clear()

    while i < n:
        consumed = state.consume_quote_or_subst(remainder, i, buf)
        if consumed:
            in_clause = True
            i += consumed
            continue
        if not state.inside_opaque():
            redirect = None
            for op in _REDIRECT_OPS:
                if remainder.startswith(op, i):
                    redirect = op
                    break
            if redirect is not None:
                if in_clause:
                    _flush()
                buf.append(redirect)
                i += len(redirect)
                in_clause = True
                continue
            sep = None
            for tok in _CLAUSE_SEPARATORS:
                if remainder.startswith(tok, i):
                    sep = tok
                    break
            if sep is not None:
                _flush()
                i += len(sep)
                in_clause = False
                if sep in _STATEMENT_SEPARATORS:
                    break
                continue
        if remainder[i].strip():
            in_clause = True
        buf.append(remainder[i])
        i += 1
    _flush()
    return out


def _clause_is_read_only(
    clause: str,
    mktemp_vars: FrozenSet[str] = frozenset(),
) -> bool:
    if not clause:
        return True
    stripped = clause.strip()
    if _STATUS_CAPTURE_RE.match(stripped):
        return True
    if "$?" in stripped:
        return False
    for op in _REDIRECT_OPS:
        if stripped.startswith(op):
            return _redirect_target_is_free(op, stripped, mktemp_vars)
    if stripped in _BEST_EFFORT_NOOP_CLAUSES:
        return True
    parts = stripped.split(maxsplit=1)
    verb = parts[0] if parts else ""
    return verb in _READ_PIPE_VERBS or verb in _BENIGN_PRINT_VERBS


def _clause_is_best_effort(
    clause: str,
    mktemp_vars: FrozenSet[str] = frozenset(),
) -> bool:
    if not clause:
        return True
    stripped = clause.strip()
    for op in _REDIRECT_OPS:
        if stripped.startswith(op):
            return _redirect_target_is_free(op, stripped, mktemp_vars)
    return stripped in _BEST_EFFORT_NOOP_CLAUSES


def _is_substantive_read_clause(
    clause: str,
    mktemp_vars: FrozenSet[str] = frozenset(),
) -> bool:
    stripped = clause.strip()
    if not stripped:
        return False
    if stripped in ("2>&1", ">&1", ">&2"):
        return False
    if _STATUS_CAPTURE_RE.match(stripped):
        return False
    if stripped in _BEST_EFFORT_NOOP_CLAUSES:
        return False
    for op in _REDIRECT_OPS:
        if stripped.startswith(op):
            target = stripped[len(op):].strip()
            if not target or target in ("1", "2"):
                return False
            return _is_free_path_target(target, mktemp_vars)
    parts = stripped.split(maxsplit=1)
    verb = parts[0] if parts else ""
    return verb in _READ_PIPE_VERBS


def _redirect_target_is_free(
    op: str,
    stripped: str,
    mktemp_vars: FrozenSet[str],
) -> bool:
    target = stripped[len(op):].strip()
    if op == "2>&1" and target == "":
        return True
    if op == ">&" and target in ("1", "2"):
        return True
    return _is_free_path_target(target, mktemp_vars)


def _is_free_path_target(
    target: str, mktemp_vars: FrozenSet[str],
) -> bool:
    if not target:
        return False
    for prefix in FREE_PATH_PREFIXES:
        if target.startswith(prefix):
            return True
    var_name = _extract_var_name(target)
    if var_name is not None and var_name in mktemp_vars:
        return True
    return False


def _extract_var_name(target: str) -> Optional[str]:
    match = _VAR_REF_RE.match(target.strip())
    return match.group(1) if match else None


__all__ = ["is_best_effort_wrapping", "is_read_wrapping",
    "is_substantive_read_wrapping", "is_write_output_consumer_only"]
