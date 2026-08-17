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

from yoke_core.hooks import session_dispatch_cursor_lifecycle as _lifecycle
from yoke_core.hooks.resume_block_dispatch import render as _render_resume_block
from yoke_core.hooks.types import HookContext


# Cursor keeps the generation stream open across a mid-turn hook and needs
# a JSON object back before it resumes. Empty stdout drops the stream.
_STREAM_SAFE_REPLY = "{}\n"


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
    """Return the concrete model the payload names, or ``""``.

    Cursor sends the literal ``"default"`` — its word for "whatever the
    user configured" — as the model on every event except
    ``afterAgentThought``, so a placeholder value is no model at all and
    callers must not store it as one.
    """
    from yoke_harness.hooks.identity import _is_placeholder_model

    for key in ("model_id", "model"):
        value = _field(payload, key)
        if value and not _is_placeholder_model(value):
            return value
    return ""


def _entrypoint() -> str:
    from yoke_harness.hooks.identity import cursor_surface_entrypoint

    return cursor_surface_entrypoint()


def _render_orientation(
    session_id: str, root: str, registration_failed: str,
) -> str:
    from yoke_core.domain.harness_capability_registry import (
        compact_entrypoint_display,
        shared_downstream_paths,
    )
    from yoke_core.hooks.session_dispatch import (
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
        return json.dumps({
            "additional_context": (
                "## Yoke Orientation (Cursor hook-enhanced)\n\n"
                "WARNING: No stable session ID available. Running in "
                "degraded mode.\nDo NOT infer your identity from the "
                "active sessions table on the board.\n"
            )
        }) + "\n"
    os.environ["YOKE_SESSION_ID"] = session_id
    if _cursor.is_folded_cursor_session(record.payload):
        return json.dumps({"additional_context": ""}) + "\n"
    err = _lifecycle.register(
        root, session_id, _payload_model(record.payload) or "unknown",
        _entrypoint(),
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
    from yoke_core.hooks import cursor_payload as _cursor
    from yoke_core.hooks import telemetry
    from yoke_core.hooks.session_dispatch import _first_prompt

    raw = _payload_json(record.payload)
    session_id = _cursor.resolve_session_id(raw)
    if not session_id:
        return ""
    if not _cursor.is_folded_cursor_session(record.payload):
        if _lifecycle.touch(root, session_id) != 0:
            _lifecycle.register(
                root, session_id, _payload_model(record.payload) or "unknown",
                _entrypoint(),
            )
        if _first_prompt(session_id, codex=False):
            telemetry.emit_harness_session_sent_first_user_prompt_submit(
                "", session_id,
            )
    return ""


def run_model_report(record: HookContext, root: str) -> str:
    """Heal a placeholder session model once a payload names a real one.

    Always replies with an empty JSON object. This event fires while the
    model stream is open, and Cursor requires a JSON reply to continue:
    an empty stdout kills the generation stream, surfacing to the operator
    as ``RetriableError: WritableIterable is closed`` rather than as
    anything hook-shaped. Measured 3/3 failed ``cursor-agent -p`` runs on
    the empty reply against 17 clean fires on ``{}``.

    Cursor multiplexes model providers, so the model a session actually
    runs under is only knowable from the event that reports it — the
    session-opening events name the ``"default"`` placeholder instead.
    Registration is idempotent and upgrade-only: an existing row heals a
    placeholder model in place and leaves a concrete one untouched, so
    this needs no read-before-write.

    The sibling ``refresh_session_model_if_placeholder`` does not apply
    here: it recovers the model from a transcript, and Cursor transcripts
    record only roles and messages. Registration is also the transport-
    correct path — it resolves the same way from a relayed hook as from a
    locally dispatched one.
    """
    from yoke_core.hooks import cursor_payload as _cursor

    model = _payload_model(record.payload)
    session_id = (
        _cursor.resolve_session_id(_payload_json(record.payload))
        if model
        else ""
    )
    if (
        model
        and session_id
        and not _cursor.is_folded_cursor_session(record.payload)
    ):
        _lifecycle.register(root, session_id, model, _entrypoint())
    return _STREAM_SAFE_REPLY
