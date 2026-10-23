"""Startup orientation for project and outside-project top-level sessions.

The client composes context from shipped packages, hook identity and local
checkout facts. It needs neither runtime source imports nor database access,
so orientation remains available when the control plane is unreachable.

Orientation carries identity, checkout and machine advisories, then pointers
for remaining questions. Full packets exceed harness inline budgets, causing
file-backed previews that deliver the tail in name only.
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
from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
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
SETUP_LINES_KEY = "_yoke_setup_lines"
REQUIRED_LINES_KEY = "_yoke_required_lines"
_GLOBAL_CONTEXT_KEY = "_yoke_global_orientation"

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


def _startup_block_lines() -> list[str]:
    """The main-session startup block delivered with session orientation.

    Orientation already leads with the machine-local advisories, and it is
    delivered once per session, so the block omits them here rather than
    repeating the same interpreter note further down the same delivery.
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
    if payload.get(_GLOBAL_CONTEXT_KEY):
        from yoke_core.domain.global_orientation import render_global_orientation

        return render_global_orientation(
            session_id, root, required_lines=payload.get(REQUIRED_LINES_KEY, [])
        )
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
    lines.extend(payload.get(REQUIRED_LINES_KEY) or [])
    branch = _git_line(root, ["branch", "--show-current"])
    branch_lines = [f"Current branch: {branch}"] if branch else []
    # One commit, not three: this block rides the inline hook channel, which
    # Codex caps at 2,500 bytes, and the required authority and trust teaching
    # comes first. `git log` is one command away for the rest.
    commits = _git_line(root, ["log", "--oneline", "-1"])
    commit_lines = ["", "Recent commit:", commits] if commits else []
    tail: list[str] = []
    if (root / ".yoke" / "BOARD.md").is_file():
        tail.extend(["", "Board available at .yoke/BOARD.md"])
    tail.extend(_startup_block_lines())
    # Queue branches and commit subjects are unbounded. Drop optional Git
    # context before it can crowd the authority/trust instructions out of
    # the smallest harness channel; the checkout identity remains intact.
    budget = min(INLINE_CONTEXT_BYTES.values())
    from yoke_core.domain.session_orientation_setup import render_with_setup

    return render_with_setup(
        lines,
        [branch_lines + commit_lines, branch_lines, []],
        tail,
        payload.get(SETUP_LINES_KEY) or [],
        budget,
    )


def orientation_for_hook(
    event_name: str,
    stdin_data: str,
    *,
    cursor: bool = False,
) -> Optional[str]:
    """Return orientation context for one harness startup event, or ``None``.

    The single entry point the hook adapter calls. Returns ``None`` — never
    raises — for every case that is not a startup event worth orienting:
    the wrong event, an unparseable payload, a session already oriented, or
    any unexpected failure. Hook delivery must not break the calling agent,
    so orientation degrades to silence. A cwd outside every project gets
    :mod:`yoke_core.domain.global_orientation` instead of the project block.
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

    from yoke_harness.hooks.identity import detect_executor

    executor = detect_executor()
    startup_event = session_orientation_event(cursor=cursor, executor=executor)
    if event_name not in (
        startup_event,
        session_orientation_redelivery_event(cursor=cursor),
    ):
        return None
    payload = loads_text(stdin_data) if stdin_data else None
    if not isinstance(payload, dict):
        return None
    if executor == "codex" and event_name == startup_event:
        if payload.get("source") == "startup" and not payload.get("transcript_path"):
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
    if orientation_delivered(session_id):
        return None
    lost_earlier = record_orientation_attempt(session_id)
    block = render_scoped_orientation(payload, Path(cwd))
    if not block:
        return None
    if event_name == startup_event and not lost_earlier:
        return block
    return _announce_redelivery(session_id, event_name) + block


def render_scoped_orientation(payload: dict[str, Any], cwd: Path) -> str:
    """Select setup facts and teaching from the actual project boundary."""
    root = _project_root(cwd)
    if root is None:
        return render_orientation({**payload, _GLOBAL_CONTEXT_KEY: True}, cwd)
    from yoke_cli.config.setup_facts_summary import orientation_lines

    return render_orientation(
        {
            **payload,
            _GLOBAL_CONTEXT_KEY: False,
            SETUP_LINES_KEY: orientation_lines(root),
        },
        root,
    )


def _project_root(start: Path) -> Optional[Path]:
    """Walk up from *start* to the checkout that owns the Yoke install.

    Project installs have a local ``.yoke`` directory; the machine's own
    state directory must never turn its home and children into a project.
    """
    try:
        current = start.resolve()
    except OSError:
        return None
    from yoke_contracts.machine_config.paths import yoke_home

    machine_state = yoke_home().resolve()
    for candidate in (current, *current.parents):
        marker = candidate / ".yoke"
        if marker.is_dir() and marker.resolve() != machine_state:
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
    "render_scoped_orientation",
]
