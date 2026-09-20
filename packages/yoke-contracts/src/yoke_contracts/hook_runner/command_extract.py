"""One command reader for every text-matching PreToolUse guard.

Engine lints and the product-local hook subset must see the same command
text. The reader lives here so harness can share it without importing
the engine. It recovers ``tool_input.command``, resolves simple
``NAME=value`` bindings, and leaves an unresolved substitution visible
instead of returning text that merely looks clean.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_UNRESOLVED_ARGV0 = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$")
_VARIABLE_REFERENCE = re.compile(
    r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}"
    r"|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)
_LITERAL_ASSIGNMENT = re.compile(
    r"(?:^|[\s;&|])(?P<name>[A-Za-z_][A-Za-z0-9_]*)="
    r"(?P<value>\"[^\"$`]*\"|'[^'$`]*'|[^\s;&|`$]*)"
    r"(?=$|[\s;&|])",
    re.MULTILINE,
)


def raw_command(payload: Mapping[str, Any] | object) -> str:
    """Return the command string from a PreToolUse payload, or ``""``."""
    if not isinstance(payload, Mapping):
        return ""
    for key in ("tool_input", "toolInput", "input"):
        tool_input = payload.get(key)
        if isinstance(tool_input, dict):
            for command_key in ("command", "cmd"):
                value = tool_input.get(command_key)
                if isinstance(value, str) and value:
                    return value
    value = payload.get("command")
    return value if isinstance(value, str) else ""


def extract_command(payload: Mapping[str, Any] | object) -> str:
    """Return the Bash command, with simple leading assignments substituted."""
    raw = raw_command(payload)
    if not raw:
        return ""
    return substitute_bound_variables(raw)


def is_unresolved_command_token(token: str) -> bool:
    """True when *token* is a command-position ``$name`` / ``${name}``."""
    if not token:
        return False
    return bool(_UNRESOLVED_ARGV0.match(token.rsplit("/", 1)[-1]))


def substitute_bound_variables(command: str) -> str:
    """Replace bound ``$name`` / ``${name}``; leave unbound names as written."""
    bindings: dict[str, str] = {}
    for match in _LITERAL_ASSIGNMENT.finditer(command):
        name = match.group("name")
        value = match.group("value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if value:
            bindings[name] = value
        else:
            bindings.pop(name, None)
    if not bindings:
        return command

    def _replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("bare")
        return bindings.get(name, match.group(0))

    return _VARIABLE_REFERENCE.sub(_replace, command)


__all__ = [
    "extract_command",
    "is_unresolved_command_token",
    "raw_command",
    "substitute_bound_variables",
]
