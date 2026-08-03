"""Cursor session-lifecycle handlers consumed by the shared dispatch.

Cursor delivers orientation through the ``sessionStart`` hook's
``additional_context`` JSON reply — the one injection channel that fires
on both Cursor surfaces (IDE chat and the non-interactive terminal
agent). Identity comes from the hook payload: the parser has already
folded subagent session ids into the top-level container, and the active
model is named per payload because Cursor multiplexes providers.

Session end routes through the shared non-destructive cleanup: the IDE
surface keeps a session open for hours without a ``sessionEnd``, and the
close reasons include transient window signals, so ending is always
"end if empty", never "assert agent gone".
"""

from __future__ import annotations

import json
import os

from runtime.harness.hook_runner import session_dispatch_cursor_lifecycle as _lifecycle
from runtime.harness.hook_runner.resume_block_dispatch import render as _render_resume_block
from runtime.harness.hook_runner.types import HookContext


def _payload_json(payload: dict) -> str:
    try:
        return json.dumps(payload)
    except TypeError:
        return "{}"


def _field(payload: dict, name: str) -> str:
    value = payload.get(name, "")
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _payload_model(payload: dict) -> str:
    return _field(payload, "model_id") or _field(payload, "model") or "unknown"


def _entrypoint() -> str:
    if os.environ.get("CURSOR_INVOKED_AS") == "cursor-agent":
        return "cursor-cli"
    return "cursor-desktop"


def _render_orientation(
    session_id: str, root: str, registration_failed: str,
) -> str:
    from yoke_core.domain.harness_capability_registry import (
        compact_entrypoint_display,
        shared_downstream_paths,
    )
    from runtime.harness.hook_runner.session_dispatch import (
        _connected_env_remediation,
        _orientation_base,
    )

    lines = _orientation_base(
        "## Yoke Orientation (Cursor hook-enhanced)", session_id, root,
        extra_files=["CURSOR.md"],
    )
    if registration_failed:
        remediation = _connected_env_remediation(registration_failed)
        warning = [
            "WARNING: Session registration failed - scheduler will not see "
            "this session.",
        ]
        warning += [remediation] if remediation else []
        lines[5:5] = [*warning, ""]
    lines[5:5] = [
        "Executor: cursor",
        "Mode: hook-enhanced (sessionStart additional_context)",
        f"Root: {root}",
        "",
    ]
    lines.extend([
        "Safe commands: " + compact_entrypoint_display(),
        "Downstream paths: " + ", ".join(shared_downstream_paths())
        + " (derived from shared registry)",
    ])
    return "\n".join(lines) + "\n"


def run_session_start(record: HookContext, root: str) -> str:
    """Register the container session and inject orientation.

    The reply is Cursor's ``sessionStart`` JSON shape: the orientation
    body travels under ``additional_context``.
    """
    from runtime.harness.cursor import cursor_hooks_payload as _cursor

    raw = _payload_json(record.payload)
    session_id = _cursor.resolve_session_id(raw)
    if not session_id:
        return json.dumps({
            "additional_context": (
                "## Yoke Orientation (Cursor hook-enhanced)\n\n"
                "WARNING: No stable session ID available. Running in "
                "degraded mode.\nDo NOT infer your identity from the "
                "active sessions table on the board.\n"
            )
        }) + "\n"
    os.environ["YOKE_SESSION_ID"] = session_id
    err = _lifecycle.register(
        root, session_id, _payload_model(record.payload), _entrypoint(),
    )
    orientation = _render_orientation(session_id, root, err)
    orientation += _render_resume_block(root, session_id, "SessionStart")
    return json.dumps({"additional_context": orientation}) + "\n"


def run_prompt_submit(record: HookContext, root: str) -> str:
    """Heartbeat + safety-net registration; no reply body.

    ``beforeSubmitPrompt`` fires on the IDE surface only, and its reply
    contract is block/allow rather than context injection — orientation
    already rode ``sessionStart`` — so this handler performs side effects
    and stays silent.
    """
    from runtime.harness.cursor import cursor_hooks_payload as _cursor
    from runtime.harness.hook_runner import telemetry
    from runtime.harness.hook_runner.session_dispatch import _first_prompt

    raw = _payload_json(record.payload)
    session_id = _cursor.resolve_session_id(raw)
    if not session_id:
        return ""
    if _lifecycle.touch(root, session_id) != 0:
        _lifecycle.register(
            root, session_id, _payload_model(record.payload), _entrypoint(),
        )
    if _first_prompt(session_id, codex=False):
        telemetry.emit_harness_session_sent_first_user_prompt_submit("", session_id)
    return ""
