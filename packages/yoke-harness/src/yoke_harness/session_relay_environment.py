"""Sanitized process environments for relay-owned native sessions."""

from __future__ import annotations

import json
import os
from typing import Mapping

from yoke_contracts.session_identity import ACTOR_ROLE_ENV_VAR, AMBIENT_ENV_VARS
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV


_PARENT_HARNESS_ENV = frozenset(
    (
        *AMBIENT_ENV_VARS,
        ACTOR_ROLE_ENV_VAR,
        RESUME_ATTEMPT_ENV,
        LAUNCH_CONTEXT_ENV,
        "YOKE_EXECUTOR",
        "YOKE_PROVIDER",
        "YOKE_MODEL",
        "CLAUDE_CODE_ENTRYPOINT",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        "CURSOR_INVOKED_AS",
        "CURSOR_CONVERSATION_ID",
        "CURSOR_TRANSCRIPT_PATH",
        "BASH_ENV",
        "ENV",
        "ZDOTDIR",
    )
)

_NATIVE_AUTOMATION_SHELL = "/bin/sh"


def native_session_environment(
    *,
    executor: str,
    provider: str | None = None,
    model: str | None = None,
    markers: Mapping[str, str] | None = None,
    launch_id: str | None = None,
    launch_attestation: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a child environment with no parent-session identity facts.

    The child is told which executor it is, never which version: a harness
    that serves a launch from a pre-warmed process pool hands the job to a
    process started long before, so a version stamped here outlives the
    binary it described. Every reader observes the surface instead.
    """
    env = dict(os.environ if environ is None else environ)
    for name in _PARENT_HARNESS_ENV:
        env.pop(name, None)
    env["SHELL"] = _NATIVE_AUTOMATION_SHELL
    env["YOKE_EXECUTOR"] = executor
    if provider:
        env["YOKE_PROVIDER"] = provider
    if model:
        env["YOKE_MODEL"] = model
    if markers:
        env.update(markers)
    if launch_id and launch_attestation:
        env[LAUNCH_CONTEXT_ENV] = json.dumps(
            {"launch_id": launch_id, "attestation": launch_attestation},
            separators=(",", ":"),
        )
    return env


__all__ = ["native_session_environment"]
