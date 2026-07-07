"""Tokenizer + registry/help classifiers for the shell-quoted-function-payload lint.

Owns the small pure helpers that decide:

* whether a Bash command is a ``--help`` invocation that should
  short-circuit the lint (S1 / Class C),
* how to tokenize the outer command body so the adapter-inventory
  scan happens on **command tokens only** (S9 / Class K),
* how to extract the canonical subcommand path that follows
  ``python(3) -m <module>`` (S10 / Class M),
* whether a registered function id is a READ shape (no side effects)
  with a fallback through :data:`TAUGHT_ADAPTERS` for sentinel
  ``internal.*`` ids,
* which variable names in the command sourced from ``$(mktemp ...)``
  so a later ``"$var"`` redirect target can be classified as free-path.

Clause-level wrapping classifiers (``is_read_wrapping``,
``is_substantive_read_wrapping``, ``is_best_effort_wrapping``) live in
the sibling :mod:`lint_shell_quoted_function_payload_wrapping` module so
both files stay under the 350-line authored-file cap.
"""

from __future__ import annotations

import re
from typing import FrozenSet, List, Optional

# Boundary tokens recognised at the outer (unquoted) shell level used by
# :func:`_find_boundary` and :func:`tokenize_outer_command`. Longer
# tokens first so ``2>&1`` matches before ``2>``. ``\n`` terminates a
# subcommand path so cleanup on the next line is not folded into the
# parsed adapter call. ``tokenize_outer_command`` already treats newline
# as whitespace before the boundary scan, so its emitted token list is
# unchanged by the listing here.
_BOUNDARY_TOKENS = (
    "2>&1", "&&", "||", ">>", "<<<", "<<-", "<<",
    "2>", ">&", "|", ">", "<", ";", "&", "\n",
)

# Canonical ``cat <free-path> | python3`` upstream that the host lint
# uses to recognise a clean file-to-stdin source as benign.
_UPSTREAM_CAT_STDIN_RE = re.compile(
    r"^\s*cat\s+(?P<path>\S+)\s*\|\s*python3?\s*$"
)


def strip_safe_cat_stdin_source(prefix: str) -> str:
    """Strip a leading ``cat <free-path> |`` source from the prefix.

    Only strips when the prefix is exactly ``cat <path> | python3``
    (clean file-to-stdin shape, no shell-variable capture or transform
    in flight) AND the path is a free-path target (``/tmp/...``,
    ``/var/folders/...``, etc.). Other paths (in-repo, ambient) keep
    the prefix intact so the lint still refuses them.
    """
    from yoke_core.domain.lint_session_cwd_validate import FREE_PATH_PREFIXES

    match = _UPSTREAM_CAT_STDIN_RE.match(prefix)
    if match is None:
        return prefix
    path = match.group("path")
    if not any(path.startswith(p) for p in FREE_PATH_PREFIXES):
        return prefix
    return ""

# Module-level cache for READ-shape lookups.
_READ_SHAPE_CACHE: dict[str, Optional[bool]] = {}


def is_help_invocation(command: str) -> bool:
    """True iff ``command`` contains a standalone ``--help``/``-h`` token."""
    if not command:
        return False
    for tok in tokenize_outer_command(command):
        if tok in ("--help", "-h"):
            return True
    return False


def tokenize_outer_command(command: str) -> List[str]:
    """Split ``command`` into outer-shell tokens.

    Quote spans, ``$(...)`` substitutions, and heredoc-body spans are
    opaque single tokens. Shell operators split tokens even without
    surrounding whitespace.
    """
    if not command:
        return []
    out: List[str] = []
    buf: List[str] = []
    state = _ScanState()
    i = 0
    n = len(command)

    def _flush() -> None:
        if buf:
            out.append("".join(buf))
            buf.clear()

    while i < n:
        ch = command[i]
        consumed = state.consume_quote_or_subst(command, i, buf)
        if consumed:
            i += consumed
            continue
        if state.inside_opaque():
            buf.append(ch)
            i += 1
            continue
        if ch in (" ", "\t", "\n"):
            _flush()
            i += 1
            continue
        boundary = None
        for tok in _BOUNDARY_TOKENS:
            if command.startswith(tok, i):
                boundary = tok
                break
        if boundary is not None:
            _flush()
            out.append(boundary)
            i += len(boundary)
            continue
        buf.append(ch)
        i += 1
    _flush()
    return out


def extract_subcommand_path(tail: str) -> str:
    """Return everything up to the first unquoted shell-syntax boundary."""
    if not tail:
        return ""
    return tail[:_find_boundary(tail)].strip()


def mktemp_bound_vars(command: str) -> FrozenSet[str]:
    """Return variable names assigned from ``$(mktemp ...)`` in ``command``.

    Used by the wrapping classifier so the canonical capture-first
    pattern (``_tmp=$(mktemp /tmp/...); cmd >"$_tmp" 2>&1``) recognises
    the redirect target as free-path. Safety is delegated to
    :mod:`path_claim_bash_temp_vars`, the same narrow helper used by the
    path-claim Bash guard.
    """
    from yoke_core.domain.path_claim_bash_temp_vars import temp_file_vars

    return temp_file_vars(command)


def is_read_shape_function(function_id: str) -> bool:
    """True iff the function id maps to a canonical READ shape.

    Live-registry lookups are authoritative — when an entry exists the
    handler's ``side_effects`` decides. For sentinel ``internal.*``
    function ids (taught-but-unregistered adapters tracked in
    :data:`TAUGHT_ADAPTERS`) the live lookup misses; in that case the
    inventory's ``read_shape`` flag decides.
    """
    cached = _READ_SHAPE_CACHE.get(function_id)
    if cached is not None:
        return cached
    try:
        from yoke_core.domain import yoke_function_registry
        entry = yoke_function_registry.lookup(function_id)
        if entry is None:
            from yoke_core.domain.handlers.__init_register__ import (
                register_all_handlers,
            )
            register_all_handlers()
            entry = yoke_function_registry.lookup(function_id)
        if entry is not None:
            result = bool(not entry.side_effects)
        else:
            result = _taught_read_shape(function_id)
    except Exception:
        result = False
    _READ_SHAPE_CACHE[function_id] = result
    return result


def _taught_read_shape(function_id: str) -> bool:
    try:
        from yoke_core.api.service_client_structured_api_adapter_inventory_taught import (
            TAUGHT_ADAPTERS,
        )
    except Exception:
        return False
    for entry in TAUGHT_ADAPTERS:
        if entry.function_id == function_id:
            return bool(entry.read_shape)
    return False


# ---------------------------------------------------------------------------
# Quote-aware scan state — shared with the wrapping module so both walk
# the same opaque-span rules.
# ---------------------------------------------------------------------------


class _ScanState:
    def __init__(self) -> None:
        self.in_single = False
        self.in_double = False
        self.paren_depth = 0

    def inside_opaque(self) -> bool:
        return self.in_single or self.in_double or self.paren_depth > 0

    def consume_quote_or_subst(
        self, src: str, i: int, sink: List[str],
    ) -> int:
        """Return the number of characters consumed by quote / subst handling.

        Zero means the caller should handle the character normally.
        ``sink`` is appended to with every absorbed character.
        """
        n = len(src)
        ch = src[i]
        if ch == "\\" and not self.in_single and i + 1 < n:
            sink.append(ch)
            sink.append(src[i + 1])
            return 2
        if self.in_single:
            sink.append(ch)
            if ch == "'":
                self.in_single = False
            return 1
        if self.in_double:
            if ch == "$" and i + 1 < n and src[i + 1] == "(":
                self.paren_depth += 1
                sink.append("$(")
                return 2
            if self.paren_depth > 0:
                if ch == "(":
                    self.paren_depth += 1
                elif ch == ")":
                    self.paren_depth -= 1
                sink.append(ch)
                return 1
            sink.append(ch)
            if ch == '"':
                self.in_double = False
            return 1
        if self.paren_depth > 0:
            if ch == "(":
                self.paren_depth += 1
            elif ch == ")":
                self.paren_depth -= 1
            sink.append(ch)
            return 1
        if ch == "'":
            self.in_single = True
            sink.append(ch)
            return 1
        if ch == '"':
            self.in_double = True
            sink.append(ch)
            return 1
        if ch == "$" and i + 1 < n and src[i + 1] == "(":
            self.paren_depth = 1
            sink.append("$(")
            return 2
        return 0


def _find_boundary(tail: str) -> int:
    state = _ScanState()
    i = 0
    n = len(tail)
    sink: List[str] = []
    while i < n:
        consumed = state.consume_quote_or_subst(tail, i, sink)
        if consumed:
            i += consumed
            continue
        if state.inside_opaque():
            i += 1
            continue
        for tok in _BOUNDARY_TOKENS:
            if tail.startswith(tok, i):
                return i
        i += 1
    return n


# Re-export the wrapping classifiers so existing callers keep importing
# from this module. Keep the bodies in the sibling — this preserves the
# public surface without inflating the line count.
from yoke_core.domain.lint_shell_quoted_function_payload_wrapping import (  # noqa: E402
    is_best_effort_wrapping,
    is_read_wrapping,
    is_substantive_read_wrapping,
    is_write_output_consumer_only,
)


__all__ = [
    "extract_subcommand_path",
    "is_best_effort_wrapping",
    "is_help_invocation",
    "is_read_shape_function",
    "is_read_wrapping",
    "is_substantive_read_wrapping",
    "is_write_output_consumer_only",
    "mktemp_bound_vars",
    "strip_safe_cat_stdin_source",
    "tokenize_outer_command",
]
