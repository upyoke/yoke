"""Turn raw shell tokens into the filesystem paths they actually name.

Both target extractors — the session-cwd walk in
:mod:`lint_session_cwd_target_extract_shell` and the write-position walk in
:mod:`lint_session_cwd_target_extract` — need the same judgment about a
single token: does it name a path a guard can validate, and if it is a
variable reference, which path is that?

The capture-first recipe every long command follows makes that judgment
load-bearing::

    _tmp=$(mktemp /tmp/yoke-cmd.XXXXXX)
    <command> >"$_tmp" 2>&1

Extraction sees the redirect operand as the literal text ``$_tmp``. A
non-absolute operand is joined with the harness cwd by the write-target
consumers, so that literal resolved to a main-checkout path and the guards
denied the recipe they document. :func:`path_target_from_token` reads the
variable's own assignment out of the same command body and returns the temp
path it names; a reference it cannot expand returns ``None`` so callers
withhold a verdict instead of inventing a cwd-relative target.

One module owns both halves because a token the two extractors disagree
about is exactly how this class of false denial returns.
"""

from __future__ import annotations

import os
import re
import shlex
import tempfile
from pathlib import PurePath
from typing import Dict, List, Mapping, Optional, Tuple


_REGEX_METACHARS = re.compile(r"[?*{]")
_MID_STRING_COLON = re.compile(r".+:.+")
_SED_ANCHOR_PREFIX = "/^"
_URL_VERSION = re.compile(r"^/v\d+/")

# ``NAME=$(mktemp …)`` / ``NAME="$(mktemp …)"`` / ``NAME=`mktemp …` ``.
_COMMAND_SUBSTITUTION_ASSIGNMENT = re.compile(
    r"(?:^|[\s;&|])(?P<name>[A-Za-z_][A-Za-z0-9_]*)="
    r"[\"']?(?:\$\((?P<paren>[^)]*)\)|`(?P<tick>[^`]*)`)",
    re.MULTILINE,
)

# ``NAME=<literal>`` with no expansion of its own. The value pattern excludes
# ``$`` and backticks so the command-substitution form above stays the only
# match for that shape.
_LITERAL_ASSIGNMENT = re.compile(
    r"(?:^|[\s;&|])(?P<name>[A-Za-z_][A-Za-z0-9_]*)="
    r"(?P<value>\"[^\"$`]*\"|'[^'$`]*'|[^\s;&|`$]*)"
    r"(?=$|[\s;&|])",
    re.MULTILINE,
)

_VARIABLE_REFERENCE = re.compile(
    r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}"
    r"|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)

# ``mktemp`` with no template generates this shape. Only the directory it
# sits in decides path authority, so a representative leaf is enough.
_ANONYMOUS_TEMP_LEAF = "tmp.XXXXXXXXXX"

_TEMP_ROOT_FLAGS = frozenset({"-t", "--tmpdir"})
_TEMP_ROOT_VALUE_FLAG = "-p"
_TMPDIR_EQUALS_PREFIX = "--tmpdir="


def is_path_like(token: str) -> bool:
    """Return True only when ``token`` looks like a real absolute path."""
    if not token or not token.startswith("/"):
        return False
    # Bare filesystem root: never a write target an agent specifies. A lone
    # ``/`` reaching here is almost always a tokenized shell / Python ``/``
    # operator (for example ``project_tree / "templates"`` surfacing from an
    # apply_patch / Write body), not a real path.
    if token == "/":
        return False
    # An expansion the resolver could not settle (``$?``, a nested ``$(…)``)
    # names no path this guard can validate.
    if "$" in token:
        return False
    if token.startswith(_SED_ANCHOR_PREFIX):
        return False
    if _URL_VERSION.match(token):
        return False
    if _REGEX_METACHARS.search(token):
        return False
    if _MID_STRING_COLON.match(token):
        return False
    return True


def shell_variable_bindings(command: str) -> Dict[str, str]:
    """Map variable names to the paths their assignments name in ``command``.

    Later assignments win, and one that resolves to nothing drops any
    earlier binding so a reassigned name reports as unresolvable rather
    than keeping a stale path.
    """
    bindings: Dict[str, str] = {}
    for _position, name, value in sorted(
        _scan_assignments(command), key=lambda entry: entry[0]
    ):
        if value:
            bindings[name] = value
        else:
            bindings.pop(name, None)
    return bindings


def expand_variables(
    token: str,
    bindings: Mapping[str, str],
) -> Optional[str]:
    """Return ``token`` with its variable references expanded, or ``None``.

    ``None`` means the token carries an expansion this module cannot settle
    — the caller has no path to validate and must withhold a verdict.
    """
    if "$" not in token:
        return token
    expanded = token
    for match in _VARIABLE_REFERENCE.finditer(token):
        value = bindings.get(match.group("braced") or match.group("bare"))
        if not value:
            return None
        expanded = expanded.replace(match.group(0), value, 1)
    return None if "$" in expanded else expanded


def path_target_from_token(
    token: str,
    bindings: Mapping[str, str],
) -> Optional[str]:
    """Return the absolute path ``token`` names, or ``None`` for no verdict."""
    expanded = expand_variables(token, bindings)
    if expanded is None or not is_path_like(expanded):
        return None
    return expanded


def resolve_write_operands(
    tokens: List[str],
    bindings: Mapping[str, str],
) -> Tuple[List[str], bool]:
    """Expand write-position operands, reporting whether any went unresolved.

    Write consumers accept relative operands (``touch notes.md`` lands under
    the harness cwd), so this keeps every expanded token rather than
    filtering to absolute paths. The flag lets a caller tell "no write
    operands" apart from "write operands naming a path we cannot resolve".
    """
    resolved: List[str] = []
    unresolved = False
    for token in tokens:
        expanded = expand_variables(token, bindings)
        if expanded is None:
            unresolved = True
            continue
        resolved.append(expanded)
    return resolved, unresolved


def _scan_assignments(command: str) -> List[Tuple[int, str, Optional[str]]]:
    """Collect ``(position, name, resolved_value)`` for every assignment."""
    out: List[Tuple[int, str, Optional[str]]] = []
    for match in _COMMAND_SUBSTITUTION_ASSIGNMENT.finditer(command):
        inner = match.group("paren")
        if inner is None:
            inner = match.group("tick") or ""
        out.append((match.start("name"), match.group("name"), _mktemp_path(inner)))
    for match in _LITERAL_ASSIGNMENT.finditer(command):
        value = match.group("value").strip("\"'")
        out.append((match.start("name"), match.group("name"), value or None))
    return out


def _mktemp_path(inner: str) -> Optional[str]:
    """Return the path an ``mktemp`` substitution creates, or ``None``.

    Any other command substitution is opaque to static analysis and binds
    nothing.
    """
    argv = _safe_split(inner)
    if not argv or PurePath(argv[0]).name != "mktemp":
        return None

    root: Optional[str] = None
    template: Optional[str] = None
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in _TEMP_ROOT_FLAGS:
            root = root or tempfile.gettempdir()
        elif token.startswith(_TMPDIR_EQUALS_PREFIX):
            root = token[len(_TMPDIR_EQUALS_PREFIX):] or tempfile.gettempdir()
        elif token == _TEMP_ROOT_VALUE_FLAG and index + 1 < len(argv):
            root = argv[index + 1]
            index += 2
            continue
        elif not token.startswith("-") and template is None:
            template = token
        index += 1

    if template and os.path.isabs(template):
        return template
    if root:
        return os.path.join(root, template or _ANONYMOUS_TEMP_LEAF)
    # A relative template with no temp-root flag lands in the working
    # directory, not the temp root — leave it relative so the caller
    # resolves it against the cwd it knows.
    if template:
        return template
    return os.path.join(tempfile.gettempdir(), _ANONYMOUS_TEMP_LEAF)


def _safe_split(text: str) -> List[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return []


__all__ = [
    "expand_variables",
    "is_path_like",
    "path_target_from_token",
    "resolve_write_operands",
    "shell_variable_bindings",
]
