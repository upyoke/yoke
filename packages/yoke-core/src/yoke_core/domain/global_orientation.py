"""Startup orientation for a session opened outside every Yoke project.

A session whose folder is not inside a project checkout still runs on a
machine where Yoke is installed. It gets one compact block: Yoke is here,
this folder is outside every project, the one next action — the
user-level ``yoke-global`` skill picks or adds the project and names the
folder where a new session does the item work — and the rules for writing to
the user, which inside a project arrive with ``AGENTS.md``.

The block is short by construction so it fits the smallest harness inline
channel beside messages and required recovery. The list of this machine's
project folders is optional: it is dropped first, then shortened, whenever
the required lines would not fit, and omitted when the machine config
cannot be read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_contracts.harness_global_skill import GLOBAL_SKILL_NAME
from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_contracts.user_writing_rules import RULES as WRITING_RULES
from yoke_core.domain.session_orientation import ORIENTATION_HEADING

DOCS_URL = "https://upyoke.com/docs"

#: Optional project folders listed before the rest is summarized.
_PROJECT_LINES = 5


def render_global_orientation(session_id: str, cwd: Path) -> str:
    """Render the outside-project orientation for one session, or ``""``."""
    if not session_id or session_id == "unknown":
        return ""
    required = [
        ORIENTATION_HEADING,
        "",
        f"Your Session: {session_id}",
        f"Yoke is installed on this machine. This folder is outside every Yoke project: {cwd}",
        "",
        "Next: ask the user what they want to work on, then use the "
        f"`{GLOBAL_SKILL_NAME}` skill to pick or add its project. Item work "
        "happens in a new session opened in that project's folder.",
        f"Machine status: `yoke status`. Command help: `yoke --help` or {DOCS_URL}.",
        "",
        f"Writing to the user: {WRITING_RULES}",
    ]
    budget = min(INLINE_CONTEXT_BYTES.values())
    folders = _project_folders()
    for count in range(min(len(folders), _PROJECT_LINES), -1, -1):
        rendered = _join(required + _project_lines(folders, count))
        if len(rendered.encode("utf-8")) <= budget:
            return rendered
    return rendered


def _project_lines(folders: list[str], count: int) -> list[str]:
    if count == 0:
        return []
    lines = ["", "Project folders on this machine:"]
    lines.extend(f"- {folder}" for folder in folders[:count])
    if len(folders) > count:
        lines.append(f"- and {len(folders) - count} more: `yoke projects list`")
    return lines


def _project_folders() -> list[str]:
    """This machine's mapped project checkouts; ``[]`` when unreadable."""
    try:
        from yoke_contracts.machine_config import schema_projects
        from yoke_contracts.machine_config.runtime import load_config

        config: Any = load_config()
        return sorted(
            {checkout for checkout, _ in schema_projects.mapped_checkouts(config)}
        )
    except Exception:  # noqa: BLE001 — optional context never blocks orientation
        return []


def _join(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["DOCS_URL", "render_global_orientation"]
