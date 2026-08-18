"""Canonicalize stored verification commands onto the sanctioned runner."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.qa_environment_declaration import SANCTIONED_RUN_SURFACE

RETIRED_WATCH_PYTEST = "python3 -m yoke_core.tools.watch_pytest"
SANCTIONED_WATCH_PYTEST = SANCTIONED_RUN_SURFACE.rstrip(" -")


def canonicalize_registered_command(command: str) -> str:
    """Rewrite the retired module form to ``yoke watch pytest``.

    Preserves arguments after the module path and drops any ``uv run``
    prefix the hook now refuses. Commands that already use the sanctioned
    surface are returned unchanged.
    """
    text = str(command).strip()
    index = text.find(RETIRED_WATCH_PYTEST)
    if index < 0:
        return text
    rest = text[index + len(RETIRED_WATCH_PYTEST):].lstrip()
    return f"{SANCTIONED_WATCH_PYTEST} {rest}".rstrip()


def rewrite_retired_watch_pytest_commands(conn: Any) -> int:
    """Rewrite stored requirement snapshots that still name the module form."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rewritten = 0
    for row in query_rows(conn, "SELECT id, method_config FROM qa_requirements"):
        try:
            config = json.loads(str(row_value(row, "method_config", "") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(config, dict):
            continue
        command = str(config.get("command") or "")
        canonical = canonicalize_registered_command(command)
        if canonical == command:
            continue
        config["command"] = canonical
        conn.execute(
            f"UPDATE qa_requirements SET method_config={marker} WHERE id={marker}",
            (json.dumps(config, sort_keys=True), int(row_value(row, "id", 0))),
        )
        rewritten += 1
    if rewritten:
        conn.commit()
    return rewritten


__all__ = [
    "RETIRED_WATCH_PYTEST",
    "SANCTIONED_WATCH_PYTEST",
    "canonicalize_registered_command",
    "rewrite_retired_watch_pytest_commands",
]
