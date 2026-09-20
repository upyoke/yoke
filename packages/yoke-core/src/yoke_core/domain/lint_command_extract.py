"""One command reader for every text-matching PreToolUse guard.

Guards used to each copy the payload walk that finds ``tool_input.command``.
They disagreed about what the command even said once a shell variable
stood in for a verb. This module is the single reader: it recovers the
text, resolves simple ``NAME=value`` bindings, and leaves an unresolved
substitution visible instead of returning text that merely looks clean.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.lint_shell_target_tokens import substitute_bound_variables

_UNRESOLVED_ARGV0 = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$")


def extract_command(payload: Mapping[str, Any] | object) -> str:
    """Return the Bash command, with simple leading assignments substituted."""
    raw = raw_command(payload)
    if not raw:
        return ""
    return substitute_bound_variables(raw)


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


def is_unresolved_command_token(token: str) -> bool:
    """True when *token* is a command-position ``$name`` / ``${name}``."""
    if not token:
        return False
    return bool(_UNRESOLVED_ARGV0.match(token.rsplit("/", 1)[-1]))
