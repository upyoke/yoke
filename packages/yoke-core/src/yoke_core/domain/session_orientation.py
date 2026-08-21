"""Startup orientation for a managed project's top-level session.

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

from yoke_contracts.hook_runner.chain_registry import session_orientation_event
from yoke_contracts.project_contract.managed_block import (
    carries_main_agent_packet,
)


ORIENTATION_HEADING = "## Yoke Orientation"

# Local-universe evaluation receives client-composed context through
# ``RunControls.payload_extra``. Cursor's lifecycle dispatcher reads this
# marker so it consumes the shared body directly only when no client body is
# already waiting to be merged into its SessionStart reply.
CLIENT_ORIENTATION_PRESENT_KEY = "_yoke_client_orientation_present"

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


def _operating_layer_advisory(root: Path) -> str:
    """One refresh notice when tracked project teaching predates this engine."""
    try:
        import yoke_core
        from yoke_contracts.engine_version import installed_engine_version
        from yoke_cli.operating_layer_drift import (
            compare_installed_layer,
            refresh_command,
        )

        comparison = compare_installed_layer(
            root,
            running_version=installed_engine_version(),
            running_module_file=str(yoke_core.__file__ or ""),
        )
    except Exception:  # noqa: BLE001 — startup orientation must fail open
        return ""
    if comparison is None or not comparison.layer_is_behind:
        return ""
    release = comparison.receipt.source_engine_release
    command = refresh_command(comparison.receipt.project_root)
    return (
        f"Yoke operating layer {release} is behind the running engine; "
        f"refresh it with `{command}`."
    )


def _advisory_lines(root: Path) -> list[str]:
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
        _operating_layer_advisory(root),
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
    lines: list[str] = _advisory_lines(root)
    lines.extend(
        [
            ORIENTATION_HEADING,
            "",
            f"Your Session: {session_id}",
            "Do NOT infer your identity from the active sessions table on the board.",
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


def orientation_for_hook(
    event_name: str,
    stdin_data: str,
    *,
    cursor: bool = False,
) -> Optional[str]:
    """Return orientation context for one harness startup event, or ``None``.

    The single entry point the hook adapter calls. Returns ``None`` — never
    raises — for every case that is not a startup event worth orienting:
    the wrong event, an unparseable payload, a non-project cwd, a session
    already oriented, or any unexpected failure. Hook delivery must not
    break the calling agent, so orientation degrades to silence.
    """
    try:
        return _orientation_for_hook(
            event_name,
            stdin_data,
            cursor=cursor,
        )
    except Exception:
        return None


def _orientation_for_hook(
    event_name: str,
    stdin_data: str,
    *,
    cursor: bool,
) -> Optional[str]:
    from yoke_core.domain.json_helper import loads_text

    if event_name != session_orientation_event(cursor=cursor):
        return None
    payload = loads_text(stdin_data) if stdin_data else None
    if not isinstance(payload, dict):
        return None
    if cursor:
        from yoke_core.hooks.cursor_payload import (
            is_folded_cursor_session,
            parse_payload,
            resolve_root,
            resolve_session_id,
        )

        payload = parse_payload(stdin_data)
        if is_folded_cursor_session(payload):
            return None
        session_id = (
            _text(payload, "container_session_id")
            or _text(payload, "session_id")
            or resolve_session_id(stdin_data)
        )
        cwd = resolve_root(stdin_data)
        if session_id:
            payload["session_id"] = session_id
    else:
        session_id = _text(payload, "session_id")
        cwd = _text(payload, "cwd")
    if not session_id or session_id == "unknown":
        return None
    if not cwd:
        return None
    root = _project_root(Path(cwd))
    if root is None:
        return None
    if not _claim_session_orientation(session_id):
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


def _claim_session_orientation(session_id: str) -> bool:
    """True once for *session_id*; arm the startup-orientation marker.

    Each hook event runs in a fresh process, so "already oriented" has to be
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
    "CLIENT_ORIENTATION_PRESENT_KEY",
    "ORIENTATION_HEADING",
    "orientation_for_hook",
    "render_orientation",
]
