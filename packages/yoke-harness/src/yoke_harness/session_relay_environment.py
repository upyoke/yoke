"""Sanitized process environments for relay-owned native sessions."""

from __future__ import annotations

import json
import os
from typing import Mapping

from yoke_contracts.session_identity import ACTOR_ROLE_ENV_VAR, AMBIENT_ENV_VARS
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV


_PARENT_HARNESS_ENV = frozenset(
    (
        *AMBIENT_ENV_VARS,
        ACTOR_ROLE_ENV_VAR,
        LAUNCH_CONTEXT_ENV,
        "YOKE_EXECUTOR",
        "YOKE_EXECUTOR_VERSION",
        "YOKE_PROVIDER",
        "YOKE_MODEL",
        "CLAUDE_CODE_ENTRYPOINT",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        "CURSOR_INVOKED_AS",
        "CURSOR_CONVERSATION_ID",
        "CURSOR_TRANSCRIPT_PATH",
    )
)


def native_session_environment(
    *,
    executor: str,
    executor_version: str,
    provider: str | None = None,
    markers: Mapping[str, str] | None = None,
    launch_id: str | None = None,
    launch_attestation: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a child environment with no parent-session identity facts."""
    env = dict(os.environ if environ is None else environ)
    for name in _PARENT_HARNESS_ENV:
        env.pop(name, None)
    env["YOKE_EXECUTOR"] = executor
    env["YOKE_EXECUTOR_VERSION"] = executor_version
    if provider:
        env["YOKE_PROVIDER"] = provider
    if markers:
        env.update(markers)
    if launch_id and launch_attestation:
        env[LAUNCH_CONTEXT_ENV] = json.dumps(
            {"launch_id": launch_id, "attestation": launch_attestation},
            separators=(",", ":"),
        )
    return env


__all__ = ["native_session_environment"]
