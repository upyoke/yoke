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

The generated packet is supplied by this client-side orientation path for
every managed session. Keeping it out of the auto-loaded rules files preserves
their harness context headroom while retaining the same startup teaching.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.hook_runner.chain_registry import (
    session_orientation_event,
    session_orientation_redelivery_event,
)
from yoke_core.domain.session_orientation_delivery import (
    confirm_orientation_delivery,
    orientation_delivered,
    record_orientation_attempt,
)


ORIENTATION_HEADING = "## Yoke Orientation"

# Stderr marker for an orientation block that reaches its session late,
# named like the hook runner's other degradation markers so one grep finds
# every startup the operator's machine did not deliver cleanly.
ORIENTATION_REDELIVERED_MARKER = "YOKE_ORIENTATION_REDELIVERED"

# Local-universe evaluation receives client-composed context through
# ``RunControls.payload_extra``. Cursor's lifecycle dispatcher reads this
# marker so it consumes the shared body directly only when no client body is
# already waiting to be merged into its SessionStart reply.
CLIENT_ORIENTATION_PRESENT_KEY = "_yoke_client_orientation_present"

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


def _packet_lines() -> list[str]:
    """The generated main-agent packet delivered with session orientation.

    Orientation already leads with the machine-local advisories, and it is
    delivered once per session, so the packet omits them here rather than
    repeating the same interpreter note further down the same block.
    """
    from yoke_core.domain.main_agent_packet import render_main_agent_block

    block = render_main_agent_block(include_advisories=False)
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
    lines.extend(_packet_lines())
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

    startup_event = session_orientation_event(cursor=cursor)
    if event_name not in (
        startup_event,
        session_orientation_redelivery_event(cursor=cursor),
    ):
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
    if orientation_delivered(session_id):
        return None
    lost_earlier = record_orientation_attempt(session_id)
    block = render_orientation(payload, root)
    if not block:
        return None
    if event_name == startup_event and not lost_earlier:
        return block
    return _announce_redelivery(session_id, event_name) + block


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


def _announce_redelivery(session_id: str, event_name: str) -> str:
    """Warn the operator about a missed orientation; label it for the agent.

    A session that started without its bearings is otherwise invisible: the
    block simply never appeared, and nothing later says so. The stderr line
    names the miss where the operator reads hook output, and the returned
    line tells the agent why its orientation is arriving mid-session rather
    than at startup.
    """
    sys.stderr.write(
        f"WARNING: {ORIENTATION_REDELIVERED_MARKER}: session {session_id} "
        "started without its orientation block; delivering it on "
        f"{event_name}.\n"
    )
    return (
        "NOTE: this session's startup orientation did not reach it. "
        "Delivering it now.\n\n"
    )


__all__ = [
    "CLIENT_ORIENTATION_PRESENT_KEY",
    "ORIENTATION_HEADING",
    "ORIENTATION_REDELIVERED_MARKER",
    "confirm_orientation_delivery",
    "orientation_for_hook",
    "render_orientation",
]
