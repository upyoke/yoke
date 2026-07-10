"""Aggregate registry for tool-shaped ``yoke`` subcommands.

Tool-shaped commands are client-local operations (git hook bodies, the
browser-QA orchestration) that carry NO dispatcher function id — the
entrypoint consults this table only after registry resolution misses.
Each owning module contributes its own token→adapter dict; this module
merges them and owns the one resolver, so adding a family never edits
the entrypoint.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from yoke_cli.commands.adapters.board import (
    TOOL_SHAPED_SUBCOMMANDS as _BOARD_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _BOARD_USAGE,
)
from yoke_cli.commands.board_art.variant import (
    TOOL_SHAPED_SUBCOMMANDS as _BOARD_ART_VARIANT_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _BOARD_ART_VARIANT_USAGE,
)
from yoke_cli.commands.checks import (
    TOOL_SHAPED_SUBCOMMANDS as _CHECK_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _CHECK_USAGE,
)
from yoke_cli.commands.connect import (
    TOOL_SHAPED_SUBCOMMANDS as _CONNECT_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _CONNECT_USAGE,
)
from yoke_cli.commands.core import (
    TOOL_SHAPED_SUBCOMMANDS as _CORE_SUBCOMMANDS,
    CORE_USAGE as _CORE_USAGE,
)
from yoke_cli.commands.git_hook import (
    AdapterFn,
    TOOL_SHAPED_SUBCOMMANDS as _GIT_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _GIT_USAGE,
)
from yoke_cli.commands.installer_local import (
    TOOL_SHAPED_SUBCOMMANDS as _INSTALLER_LOCAL_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _INSTALLER_LOCAL_USAGE,
)
from yoke_cli.commands.local_universe import (
    TOOL_SHAPED_SUBCOMMANDS as _LOCAL_UNIVERSE_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _LOCAL_UNIVERSE_USAGE,
)
from yoke_cli.commands.merge_audit import (
    TOOL_SHAPED_SUBCOMMANDS as _MERGE_AUDIT_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _MERGE_AUDIT_USAGE,
)
from yoke_cli.commands.qa_browser import (
    QA_BROWSER_SUBCOMMANDS as _QA_BROWSER_SUBCOMMANDS,
    QA_BROWSER_USAGE as _QA_BROWSER_USAGE,
)
from yoke_cli.commands.qa_browser_lifecycle import (
    QA_BROWSER_LIFECYCLE_SUBCOMMANDS as _QA_BROWSER_LIFECYCLE_SUBCOMMANDS,
    QA_BROWSER_LIFECYCLE_USAGE as _QA_BROWSER_LIFECYCLE_USAGE,
)
from yoke_cli.commands.resync import (
    TOOL_SHAPED_SUBCOMMANDS as _RESYNC_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _RESYNC_USAGE,
)
from yoke_cli.commands.schema_converge import (
    TOOL_SHAPED_SUBCOMMANDS as _SCHEMA_CONVERGE_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _SCHEMA_CONVERGE_USAGE,
)
from yoke_cli.commands.self_host import (
    TOOL_SHAPED_SUBCOMMANDS as _SELF_HOST_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _SELF_HOST_USAGE,
)
from yoke_cli.commands.universe_ui import (
    TOOL_SHAPED_SUBCOMMANDS as _UNIVERSE_UI_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _UNIVERSE_UI_USAGE,
)
from yoke_cli.commands.usher_reconcile import (
    TOOL_SHAPED_SUBCOMMANDS as _USHER_RECONCILE_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _USHER_RECONCILE_USAGE,
)

TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    **_BOARD_SUBCOMMANDS,
    **_BOARD_ART_VARIANT_SUBCOMMANDS,
    **_CHECK_SUBCOMMANDS,
    **_CONNECT_SUBCOMMANDS,
    **_CORE_SUBCOMMANDS,
    **_GIT_SUBCOMMANDS,
    **_INSTALLER_LOCAL_SUBCOMMANDS,
    **_LOCAL_UNIVERSE_SUBCOMMANDS,
    **_MERGE_AUDIT_SUBCOMMANDS,
    **_QA_BROWSER_LIFECYCLE_SUBCOMMANDS,
    **_QA_BROWSER_SUBCOMMANDS,
    **_RESYNC_SUBCOMMANDS,
    **_SCHEMA_CONVERGE_SUBCOMMANDS,
    **_SELF_HOST_SUBCOMMANDS,
    **_UNIVERSE_UI_SUBCOMMANDS,
    **_USHER_RECONCILE_SUBCOMMANDS,
}

# cli form -> one-line usage for `yoke --help`.
TOOL_SHAPED_USAGE: Dict[str, str] = {
    **_BOARD_USAGE,
    **_BOARD_ART_VARIANT_USAGE,
    **_CHECK_USAGE,
    **_CONNECT_USAGE,
    **_CORE_USAGE,
    **_GIT_USAGE,
    **_INSTALLER_LOCAL_USAGE,
    **_LOCAL_UNIVERSE_USAGE,
    **_MERGE_AUDIT_USAGE,
    **_QA_BROWSER_LIFECYCLE_USAGE,
    **_QA_BROWSER_USAGE,
    **_RESYNC_USAGE,
    **_SCHEMA_CONVERGE_USAGE,
    **_SELF_HOST_USAGE,
    **_UNIVERSE_UI_USAGE,
    **_USHER_RECONCILE_USAGE,
}


def resolve_tool_shaped(
    argv_head: List[str],
) -> Optional[Tuple[AdapterFn, List[str]]]:
    """Match a tool-shaped subcommand at the head of ``argv_head``.

    Longest token tuple wins. Returns ``(adapter, remaining_argv)`` or
    ``None`` when no tool-shaped token tuple prefixes the input.
    """
    for length in (4, 3, 2, 1):
        if len(argv_head) < length:
            continue
        candidate = tuple(argv_head[:length])
        if candidate in TOOL_SHAPED_SUBCOMMANDS:
            return TOOL_SHAPED_SUBCOMMANDS[candidate], argv_head[length:]
    return None


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "resolve_tool_shaped",
]
