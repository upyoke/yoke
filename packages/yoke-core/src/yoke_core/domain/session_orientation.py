"""First-prompt orientation for a managed project's top-level session.

A Yoke source checkout renders startup orientation from its own harness
tree. A managed project has no such tree: its hooks relay every event to
the server, and the server cannot see that machine's git state, working
tree, or PATH — so the orientation policy is delegated back to the client
and skipped server-side. Without a client-side renderer the top-level
session of a managed project starts with no orientation at all, while its
subagents (whose adapters ship pre-rendered) start fully oriented.

This module closes that gap from the operator's own machine, using only
the shipped core package. Two deliberate constraints follow from where it
runs — inside a short-lived hook process on a machine that may have
nothing but the wheels installed:

* **No ``runtime.*`` imports.** That tree is the Yoke source repo and is
  absent from every managed project.
* **No database.** Orientation is built from the hook payload, the
  filesystem, and ``git``; a project whose control plane is unreachable
  still gets oriented rather than getting nothing.

The packet is normally supplied for free by the managed doctrine block the
install bundle composes, so this path adds it only when the project's
rules files do not already carry it — see :func:`_packet_lines`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.hook_runner.chain_registry import (
    SESSION_ORIENTATION_EVENT,
)
from yoke_contracts.project_contract.managed_block import (
    carries_main_agent_packet,
)


ORIENTATION_HEADING = "## Yoke Orientation"

# Rules files the install bundle writes the managed doctrine block into.
# Presence of the packet marker in ANY of them means the harness already
# auto-loads the packet and this path must not send a second copy.
_RULES_FILES = ("AGENTS.md", "CLAUDE.md")

_GIT_TIMEOUT_S = 5


def _text(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    return "" if value is None else str(value)


def _git_line(root: Path, args: list[str]) -> str:
    """Return one line of ``git`` output, or ``""`` on any failure.

    Orientation is best-effort context, never a gate: a project that is
    not a git checkout, or a machine with no ``git``, still gets the rest.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip("\n").strip()


def _read_rules_text(root: Path) -> str:
    """Concatenate the managed rules files that exist, for marker detection."""
    parts: list[str] = []
    for name in _RULES_FILES:
        try:
            parts.append((root / name).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(parts)


def _advisory_lines() -> list[str]:
    """Machine-local install/interpreter advisories, newest problem first.

    These probe the machine this hook runs on, which is exactly why they
    belong here and not in the server-rendered doctrine block.
    """
    from yoke_core.domain.main_agent_packet import (
        render_install_advisory_block,
        render_interpreter_advisory_block,
    )

    lines: list[str] = []
    for block in (
        render_interpreter_advisory_block(),
        render_install_advisory_block(),
    ):
        if block:
            lines.extend([block, ""])
    return lines


def _packet_lines(root: Path) -> list[str]:
    """The main-agent packet, but only when the rules files lack it.

    The install bundle composes the packet into the managed doctrine block,
    which the harness auto-loads — so on a current install this returns
    nothing and the session pays no context cost. A project installed
    before the packet shipped, or one whose bundle render degraded, has no
    marker; there this path is the only thing standing between the session
    and confabulated table names.
    """
    if carries_main_agent_packet(_read_rules_text(root)):
        return []
    from yoke_core.domain.main_agent_packet import render_main_agent_block

    block = render_main_agent_block()
    return ["", block] if block else []


def render_orientation(payload: dict[str, Any], root: Path) -> str:
    """Render the orientation block for one session, or ``""``.

    ``payload`` is the raw hook payload; ``root`` is the project checkout
    the hook fired in. Returns ``""`` when there is no session id to orient,
    since every downstream instruction is keyed to that identity.
    """
    session_id = _text(payload, "session_id")
    if not session_id or session_id == "unknown":
        return ""
    lines: list[str] = _advisory_lines()
    lines.extend(
        [
            ORIENTATION_HEADING,
            "",
            f"Your Session: {session_id}",
            "Do NOT infer your identity from the active sessions table "
            "on the board.",
            "",
            f"Root: {root}",
        ]
    )
    branch = _git_line(root, ["branch", "--show-current"])
    if branch:
        lines.append(f"Current branch: {branch}")
    commits = _git_line(root, ["log", "--oneline", "-3"])
    if commits:
        lines.extend(["", "Recent commits:", commits])
    if (root / ".yoke" / "BOARD.md").is_file():
        lines.extend(["", "Board available at .yoke/BOARD.md"])
    lines.extend(_packet_lines(root))
    return "\n".join(lines).rstrip() + "\n"


def orientation_for_hook(event_name: str, stdin_data: str) -> Optional[str]:
    """Return orientation context for one hook event, or ``None``.

    The single entry point the hook adapter calls. Returns ``None`` — never
    raises — for every case that is not a first prompt worth orienting:
    the wrong event, an unparseable payload, a non-project cwd, a session
    already oriented, or any unexpected failure. Hook delivery must not
    break the calling agent, so orientation degrades to silence.
    """
    try:
        return _orientation_for_hook(event_name, stdin_data)
    except Exception:
        return None


def _orientation_for_hook(event_name: str, stdin_data: str) -> Optional[str]:
    from yoke_core.domain.json_helper import loads_text

    if event_name != SESSION_ORIENTATION_EVENT:
        return None
    payload = loads_text(stdin_data) if stdin_data else None
    if not isinstance(payload, dict):
        return None
    session_id = _text(payload, "session_id")
    if not session_id or session_id == "unknown":
        return None
    cwd = _text(payload, "cwd")
    if not cwd:
        return None
    root = _project_root(Path(cwd))
    if root is None:
        return None
    if not _claim_first_prompt(session_id):
        return None
    return render_orientation(payload, root) or None


def _project_root(start: Path) -> Optional[Path]:
    """Walk up from *start* to the checkout that owns the Yoke install.

    A managed project is identified by its project-local ``.yoke``
    directory — the one surface `yoke project install` always creates.
    Hooks fire with the agent's cwd, which may be a subdirectory.
    """
    try:
        current = start.resolve()
    except OSError:
        return None
    for candidate in (current, *current.parents):
        if (candidate / ".yoke").is_dir():
            return candidate
    return None


def _claim_first_prompt(session_id: str) -> bool:
    """True the first time *session_id* asks; arm the marker so it is once.

    Each hook event runs in a fresh process, so "first prompt" has to be
    filesystem state. A marker that cannot be written degrades toward
    orienting again rather than never — a duplicated orientation block is
    recoverable, a session that never gets one is not.
    """
    from yoke_core.domain.project_scratch_dir import hook_marker_path

    marker = hook_marker_path(f"session-orientation-{session_id}")
    if marker.exists():
        return False
    try:
        marker.touch()
    except OSError:
        pass
    return True


__all__ = [
    "ORIENTATION_HEADING",
    "orientation_for_hook",
    "render_orientation",
]
