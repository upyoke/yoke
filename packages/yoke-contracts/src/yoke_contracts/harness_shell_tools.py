"""Which shell each harness's shell tool runs, so guards parse the right syntax.

Every shell tool feeds the one ``Bash`` guard chain, but the command text is
written for a particular shell. Claude Code names its tools after the shell
(``Bash`` runs Bash, Git Bash on Windows; ``PowerShell`` runs PowerShell).
Codex (``Bash`` in its hook payload, ``shell`` natively) and Cursor
(``Shell``, or its ``beforeShellExecution`` gate) run the machine's default
shell: PowerShell on Windows, Bash elsewhere.

This module is the single source. The renderer copies each harness's entry
into ``runtime/harness/<dir>/manifest.json`` as ``shell_tools`` (see
``runtime/harness/manifest-schema.md``). The hook client stamps the resolved
kind onto hook stdin as :data:`SHELL_KIND_PAYLOAD_KEY` before any evaluation,
local or relayed, because only the client knows its own operating system.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

ShellKind = Literal["bash", "powershell"]
ShellDeclaration = Literal["bash", "powershell", "os_default"]

SHELL_KIND_BASH: ShellKind = "bash"
SHELL_KIND_POWERSHELL: ShellKind = "powershell"
SHELL_KINDS: frozenset[str] = frozenset({SHELL_KIND_BASH, SHELL_KIND_POWERSHELL})
OS_DEFAULT: ShellDeclaration = "os_default"

#: Hook payload key carrying the client-resolved shell kind.
SHELL_KIND_PAYLOAD_KEY = "yoke_shell_kind"

#: The guard-chain matcher every shell tool resolves to.
SHELL_CHAIN_MATCHER = "Bash"

# ``""`` is a shell gate that carries no tool name (Cursor
# ``beforeShellExecution``).
HARNESS_SHELL_TOOLS: Mapping[str, Mapping[str, ShellDeclaration]] = {
    "claude-code": {"Bash": SHELL_KIND_BASH, "PowerShell": SHELL_KIND_POWERSHELL},
    "codex": {"Bash": OS_DEFAULT, "shell": OS_DEFAULT},
    "cursor": {"Shell": OS_DEFAULT, "Bash": OS_DEFAULT, "": OS_DEFAULT},
}

#: Every native shell tool name any harness sends.
SHELL_TOOL_NAMES: frozenset[str] = frozenset(
    name for tools in HARNESS_SHELL_TOOLS.values() for name in tools if name
)


def is_windows() -> bool:
    """True when this process runs on native Windows."""
    return os.name == "nt"


def shell_tools(harness_id: str) -> Mapping[str, ShellDeclaration]:
    """Return one harness's declaration; an unknown harness is a named refusal."""
    try:
        return HARNESS_SHELL_TOOLS[harness_id]
    except KeyError:
        raise KeyError(
            f"no shell_tools declared for harness {harness_id!r}; add it to "
            "yoke_contracts.harness_shell_tools and re-render the harness manifests"
        ) from None


def shell_kind_for(harness_id: str, tool_name: str, *, windows: bool) -> ShellKind | None:
    """Return the shell a harness's tool runs, or ``None`` for a non-shell tool."""
    declared = HARNESS_SHELL_TOOLS.get(harness_id, {}).get(tool_name)
    if declared is None:
        return None
    if declared == OS_DEFAULT:
        return SHELL_KIND_POWERSHELL if windows else SHELL_KIND_BASH
    return declared


def payload_shell_kind(payload: Mapping[str, object]) -> ShellKind:
    """Return the shell a hook payload's command is written for.

    The client stamp decides. Without one (a client older than the stamp),
    only Claude's ``PowerShell`` tool names its shell; anything else is Bash.
    """
    value = payload.get(SHELL_KIND_PAYLOAD_KEY)
    if value == SHELL_KIND_POWERSHELL or (
        value is None and payload.get("tool_name") == "PowerShell"
    ):
        return SHELL_KIND_POWERSHELL
    return SHELL_KIND_BASH


def manifest_shell_tools(harness_id: str) -> dict[str, str]:
    """The manifest ``shell_tools`` block: native tool name -> declaration."""
    return {name or "(shell gate)": kind for name, kind in shell_tools(harness_id).items()}


__all__ = [
    "HARNESS_SHELL_TOOLS",
    "OS_DEFAULT",
    "SHELL_CHAIN_MATCHER",
    "SHELL_KINDS",
    "SHELL_KIND_BASH",
    "SHELL_KIND_PAYLOAD_KEY",
    "SHELL_KIND_POWERSHELL",
    "SHELL_TOOL_NAMES",
    "ShellDeclaration",
    "ShellKind",
    "is_windows",
    "manifest_shell_tools",
    "payload_shell_kind",
    "shell_kind_for",
    "shell_tools",
]
