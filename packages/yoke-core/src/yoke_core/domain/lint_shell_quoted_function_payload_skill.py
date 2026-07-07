"""Skill-orchestrated adapter hints for the shell payload lint."""

from __future__ import annotations

import shlex
from typing import Optional

from yoke_core.domain.lint_shell_quoted_function_payload_classify import (
    extract_subcommand_path,
    tokenize_outer_command,
)
from yoke_core.domain.lint_shell_quoted_function_payload_messages import (
    build_skill_orchestrated_note,
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
            if outer_tokens[start:start + len(prefix)] == list(prefix):
                idx = command.find(joined)
                if idx >= 0:
                    return command[idx + len(joined):]
    return None


def skill_orchestrated_note(command: str) -> Optional[str]:
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
    if not entry or entry.agent_path != "skill-orchestrated":
        return None
    return build_skill_orchestrated_note(
        f"{_DB_ROUTER_MODULE} {' '.join(tokens)}",
        entry.function_id,
        entry.canonical_skill_invocation,
        entry.direct_use_caveat,
    )
