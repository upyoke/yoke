"""Recognize Bash variables that hold scratch temp-file paths.

Narrow shapes recognised:

* ``var=$(mktemp /tmp/template.XXXXXX)`` — explicit free-path template.
* ``var=$(mktemp ${TMPDIR:-/tmp}/template.XXXXXX)`` — explicit free-path
  template via ``$TMPDIR`` expansion.
* ``var=$(mktemp)`` and ``var=$(mktemp -d)`` — bare invocation. Bare
  ``mktemp`` defaults to ``$TMPDIR`` which on every platform Yoke
  targets is itself a free-path prefix (``/tmp`` on Linux,
  ``/var/folders/.../T/...`` on macOS), so the resulting target is
  always safe to treat as free-path.

The shape ``var=$(mktemp -p /custom/non-tmp/dir)`` is rejected — the
operator explicitly redirected the target outside the free-path
allowlist. Surrounding double quotes / single quotes around the
``$var`` reference are tolerated so redirect targets like ``"$_msg"``
that flow through the heredoc-aware extractor still match.
"""

from __future__ import annotations

import re
from typing import Collection, FrozenSet

from yoke_core.domain.lint_session_cwd_validate import FREE_PATH_PREFIXES


_VAR_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_MKTEMP_ASSIGN_RE = re.compile(
    rf"(?P<name>{_VAR_NAME})=\$\(\s*mktemp(?P<args>[^)]*)\)"
)
_VAR_REF_RE = re.compile(
    rf"""^['"]?\$(?:\{{(?P<braced>{_VAR_NAME})\}}|(?P<plain>{_VAR_NAME}))['"]?$"""
)


def temp_file_vars(command: str) -> FrozenSet[str]:
    """Return variable names assigned from ``mktemp`` that resolve to free path."""
    if not command:
        return frozenset()
    out: set[str] = set()
    for match in _MKTEMP_ASSIGN_RE.finditer(command):
        args = match.group("args") or ""
        if _is_safe_mktemp_args(args):
            out.add(match.group("name"))
    return frozenset(out)


def is_temp_file_var_ref(token: str, vars_from_mktemp: Collection[str]) -> bool:
    """Return True for ``$name`` / ``${name}`` refs (quoted or bare) to temp vars."""
    if not token or not vars_from_mktemp:
        return False
    match = _VAR_REF_RE.match(token.strip())
    if match is None:
        return False
    name = match.group("braced") or match.group("plain")
    return name in vars_from_mktemp


def _is_safe_mktemp_args(args: str) -> bool:
    """True iff mktemp args resolve to a free-path target.

    * Empty / flag-only args (``mktemp``, ``mktemp -d``) — bare
      invocation defaults to ``$TMPDIR``.
    * Positional template under Yoke's free-path allowlist or ``${TMPDIR``.
    * ``-p <dir>`` only when ``<dir>`` is itself under that allowlist or
      ``${TMPDIR``.
    """
    stripped = args.strip()
    if not stripped:
        return True
    tokens = stripped.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-p":
            if i + 1 >= len(tokens):
                return False
            target = tokens[i + 1].strip("'\"")
            if not _is_safe_temp_target(target):
                return False
            i += 2
            continue
        if tok.startswith("-p") and len(tok) > 2:
            target = tok[2:].strip("'\"")
            if not _is_safe_temp_target(target):
                return False
            i += 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        cleaned = tok.strip("'\"")
        if not _is_safe_temp_target(cleaned):
            return False
        i += 1
    return True


def _is_safe_temp_target(target: str) -> bool:
    if target.startswith("${TMPDIR"):
        return True
    return any(target.startswith(prefix) for prefix in FREE_PATH_PREFIXES)


__all__ = ["is_temp_file_var_ref", "temp_file_vars"]
