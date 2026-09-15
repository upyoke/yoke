"""Sanitized process environments for relay-owned native sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from yoke_cli.config.session_relay_instance import RELAY_STATE_DIR_ENV
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


#: What the relay exports so its own imports resolve to the release it
#: selected. A relay-internal Python process needs them; the foreign CLI it
#: starts must not have them, or that CLI's project tooling (`uv run
#: --active` is the observed case) treats the relay's release as the
#: environment of the project it is working in.
_RELAY_PYTHON_ACTIVATION_ENV = ("VIRTUAL_ENV", "PYTHONPATH")


def _without_relay_owned_path_entries(path_value: str, state_dir: str) -> str:
    """Drop the search-path entries that live inside the relay's own tree.

    The relay puts its launch link's ``bin`` ahead of the machine's own
    directories so launchd can find it, and that directory holds a
    ``python`` as well as a ``yoke``. Entries outside the relay's tree are
    the user's and stay, including whichever installed launcher the machine
    already resolves ``yoke`` through.
    """
    owned = Path(state_dir)
    kept = [
        entry
        for entry in path_value.split(os.pathsep)
        if not (
            entry and Path(entry).is_absolute() and Path(entry).is_relative_to(owned)
        )
    ]
    return os.pathsep.join(kept)


def strip_relay_owned_python_state(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return ``env`` with nothing of the relay's own Python left in it.

    Call this at the boundary where a relay-internal process starts an
    actual foreign CLI binary — and only there. The relay's supervisor and
    its detached workers start on the stable runtime interpreter, which has
    no packages of its own and imports itself through exactly the
    activation state this drops; stripping it before one of those starts
    breaks the process rather than the leak.

    The relay names the tree it owns rather than leaving it to be inferred:
    the activation variables always go, and the search path is filtered
    only when the relay declared its own root. That declaration is dropped
    too, so a worker never reads it as an invitation to write there.
    """
    result = dict(os.environ if env is None else env)
    for name in _RELAY_PYTHON_ACTIVATION_ENV:
        result.pop(name, None)
    state_dir = result.pop(RELAY_STATE_DIR_ENV, "").strip()
    search_path = result.get("PATH", "")
    if state_dir and search_path:
        result["PATH"] = _without_relay_owned_path_entries(search_path, state_dir)
    return result


def native_session_environment(
    *,
    executor: str,
    provider: str | None = None,
    model: str | None = None,
    markers: Mapping[str, str] | None = None,
    launch_id: str | None = None,
    launch_attestation: str | None = None,
    resume_attempt_id: str | None = None,
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
    if resume_attempt_id:
        env[RESUME_ATTEMPT_ENV] = resume_attempt_id
    if launch_id and launch_attestation:
        env[LAUNCH_CONTEXT_ENV] = json.dumps(
            {"launch_id": launch_id, "attestation": launch_attestation},
            separators=(",", ":"),
        )
    return env


__all__ = ["native_session_environment", "strip_relay_owned_python_state"]
