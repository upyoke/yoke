"""Cursor session-lifecycle handlers consumed by the shared dispatch.

Cursor delivers orientation through the ``sessionStart`` hook's
``additional_context`` JSON reply — the one injection channel that fires
on both Cursor surfaces (IDE chat and the non-interactive terminal
agent), and the only one a resumed print-mode turn reaches before its
first tool call. Identity comes from the hook payload: the parser has
already folded subagent session ids into the top-level container, and the
active model is named per payload because Cursor multiplexes providers.

Session end routes through the shared non-destructive cleanup: the IDE
surface keeps a session open for hours without a ``sessionEnd``, and the
close reasons include transient window signals, so ending is always
"end if empty", never "assert agent gone".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from yoke_contracts.session_model_facts import SessionModelFacts

from yoke_core.hooks import session_dispatch_cursor_lifecycle as _lifecycle
from yoke_core.hooks.resume_block_dispatch import render as _render_resume_block
from yoke_core.hooks.types import HookContext


def _payload_json(payload: dict) -> str:
    try:
        return json.dumps(payload)
    except TypeError:
        return "{}"


def _model_facts(payload: dict) -> SessionModelFacts:
    """Return the ask plus whatever the conversation store proves served.

    Cursor's hook payload names a bare family id that is neither: the ask
    lives in the launch environment and the served variant is written per
    conversation by Cursor itself, so neither is taken from stdin.
    """
    from yoke_harness.hooks.identity_relay import resolve_model_facts

    return resolve_model_facts(payload, "cursor")


def _entrypoint() -> str:
    from yoke_harness.hooks.identity import cursor_surface_entrypoint

    return cursor_surface_entrypoint()


def _render_orientation(
    record: HookContext,
    root: str,
    registration_failed: str,
) -> str:
    from yoke_core.domain.session_orientation import (
        CLIENT_ORIENTATION_PRESENT_KEY,
        render_orientation,
    )
    from yoke_core.hooks.session_dispatch_orientation import (
        _connected_env_remediation,
    )

    blocks: list[str] = []
    if registration_failed:
        remediation = _connected_env_remediation(registration_failed)
        warning = [
            "WARNING: Session registration failed - scheduler will not see "
            "this session.",
        ]
        warning += [remediation] if remediation else []
        blocks.append("\n".join(warning))
    if not record.payload.get(CLIENT_ORIENTATION_PRESENT_KEY):
        orientation = render_orientation(record.payload, Path(root)).strip()
        if orientation:
            blocks.append(orientation)
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def run_session_start(record: HookContext, root: str) -> str:
    """Register the container session and inject orientation.

    The reply is Cursor's ``sessionStart`` JSON shape: the orientation
    body travels under ``additional_context``.

    Task/subagent and linked-worktree remount sessionStart events (parser
    sets ``is_subagent_session`` / ``is_worktree_remap_session``) must not
    register: the container chat owns the ``harness_sessions`` row. Pin the
    container id for same-process follow-on and reply without orientation
    injection.
    """
    from yoke_core.hooks import cursor_payload as _cursor

    raw = _payload_json(record.payload)
    session_id = _cursor.resolve_session_id(raw)
    if not session_id:
        return (
            json.dumps(
                {
                    "additional_context": (
                        "## Yoke Orientation (Cursor hook-enhanced)\n\n"
                        "WARNING: No stable session ID available. Running in "
                        "degraded mode.\nDo NOT infer your identity from the "
                        "active sessions table on the board.\n"
                    )
                }
            )
            + "\n"
        )
    os.environ["YOKE_SESSION_ID"] = session_id
    if _cursor.is_folded_cursor_session(record.payload):
        return json.dumps({"additional_context": ""}) + "\n"
    err = _lifecycle.register(
        root,
        session_id,
        _model_facts(record.payload),
        _entrypoint(),
    )
    orientation = _render_orientation(record, root, err)
    orientation += _render_resume_block(root, session_id, "SessionStart")
    return json.dumps({"additional_context": orientation}) + "\n"


def run_prompt_submit(record: HookContext, root: str) -> str:
    """First-prompt model heal only; no reply body and no heartbeat.

    ``beforeSubmitPrompt`` fires on the IDE surface only, and its reply
    contract is block/allow rather than context injection — orientation
    already rode ``sessionStart`` — so this handler performs side effects
    and stays silent. A wake-injected prompt is not session activity, so
    later prompts must not stamp ``last_heartbeat``.
    """
    from yoke_core.hooks import cursor_payload as _cursor
    from yoke_core.hooks import telemetry
    from yoke_core.hooks.session_dispatch import _first_prompt

    raw = _payload_json(record.payload)
    session_id = _cursor.resolve_session_id(raw)
    if not session_id:
        return ""
    if not _cursor.is_folded_cursor_session(record.payload):
        facts = _model_facts(record.payload)
        first_prompt = _first_prompt(session_id, codex=False)
        # The served columns fill in rather than overwrite, so the first
        # prompt is a free chance to attest a session that opened before
        # its conversation store existed. Later prompts do not heartbeat.
        if first_prompt and facts.model:
            _lifecycle.register(root, session_id, facts, _entrypoint())
        if first_prompt:
            telemetry.emit_harness_session_sent_first_user_prompt_submit(
                "",
                session_id,
            )
    return ""
