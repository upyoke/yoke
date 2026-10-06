"""Lifecycle-transition adapter hint for the shell payload lint."""

from __future__ import annotations

import shlex
from typing import Optional

from yoke_core.domain.lint_shell_quoted_function_payload_classify import (
    extract_subcommand_path,
    tokenize_outer_command,
)
from yoke_core.domain.lint_shell_quoted_function_payload_messages import (
    build_lifecycle_transition_note,
)
from yoke_core.api.service_client_structured_api_adapter_inventory import adapter_index


_DB_ROUTER_MODULE = "yoke_core.cli.db_router"
_LIFECYCLE_FUNCTION_ID = "lifecycle.transition.execute"
_INVENTORY_BY_FUNCTION = adapter_index()


def _db_router_tail(command: str) -> Optional[str]:
    outer_tokens = tokenize_outer_command(command)
    for prefix in (
        ("python3", "-m", _DB_ROUTER_MODULE),
        ("python", "-m", _DB_ROUTER_MODULE),
    ):
        if len(outer_tokens) < len(prefix):
            continue
        joined = " ".join(prefix)
        for start in range(len(outer_tokens) - len(prefix) + 1):
            if outer_tokens[start : start + len(prefix)] == list(prefix):
                idx = command.find(joined)
                if idx >= 0:
                    return command[idx + len(joined) :]
    return None


def lifecycle_transition_note(command: str) -> Optional[str]:
    """Point a raw item-adapter status write at the lifecycle transition."""
    tail = _db_router_tail(command)
    if tail is None:
        return None
    try:
        tokens = shlex.split(extract_subcommand_path(tail))
    except ValueError:
        return None
    if len(tokens) < 5 or tokens[:2] != ["items", "update"] or tokens[3] != "status":
        return None
    entry = _INVENTORY_BY_FUNCTION.get(_LIFECYCLE_FUNCTION_ID)
    if not entry:
        return None
    return build_lifecycle_transition_note(
        f"{_DB_ROUTER_MODULE} {' '.join(tokens)}",
        entry.function_id,
        entry.cli_invocation,
    )
