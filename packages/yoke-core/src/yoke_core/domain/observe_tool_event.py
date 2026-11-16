"""Harness-neutral tool-event vocabulary used by policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Any shell tool; ``ToolEventRecord.shell_kind`` names which shell.
TOOL_KIND_SHELL = "shell"
TOOL_KIND_WRITE = "write"
TOOL_KIND_EDIT = "edit"
TOOL_KIND_APPLY_PATCH = "apply_patch"
TOOL_KINDS: Tuple[str, ...] = (
    TOOL_KIND_SHELL,
    TOOL_KIND_WRITE,
    TOOL_KIND_EDIT,
    TOOL_KIND_APPLY_PATCH,
)


@dataclass
class ToolEventRecord:
    """Harness-neutral tool-event payload consumed by the policy pipeline."""

    tool_kind: str = ""
    changed_paths: List[str] = field(default_factory=list)
    command: str = ""
    patch_body: str = ""
    tool_name: str = ""
    session_id: str = ""
    tool_use_id: Optional[str] = None
    turn_id: Optional[str] = None
    cwd: str = ""
    project_dir: str = ""
    # ``bash`` or ``powershell`` for a shell record (see harness_shell_tools).
    shell_kind: str = "bash"


__all__ = [
    "TOOL_KIND_APPLY_PATCH",
    "TOOL_KIND_EDIT",
    "TOOL_KIND_SHELL",
    "TOOL_KIND_WRITE",
    "TOOL_KINDS",
    "ToolEventRecord",
]
