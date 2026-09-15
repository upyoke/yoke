"""Sanitized process environments for relay-owned native sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
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
        # The relay entrypoint stamps these onto its own process so its
        # imports resolve to the release it selected. Inherited by a native
        # worker, they make that worker's own tooling (e.g. `uv run
        # --active`) treat the relay's release as its own project
        # environment instead of the project it is actually working in.
        "VIRTUAL_ENV",
        "PYTHONPATH",
    )
)

_NATIVE_AUTOMATION_SHELL = "/bin/sh"


def _relay_owned_state_dir(env: Mapping[str, str]) -> Path | None:
    """The relay instance's own state directory, named by its VIRTUAL_ENV.

    The relay entrypoint sets ``VIRTUAL_ENV`` to its selected release,
    ``<state_dir>/releases/<hash>``, so the release's grandparent is that
    same state directory — the root every bin directory the relay puts
    ahead of its own PATH (its launch link, runtime, and release) sits one
    level under.
    """
    virtual_env = env.get("VIRTUAL_ENV", "").strip()
    if not virtual_env:
        return None
    state_dir = Path(virtual_env).parent.parent
    return state_dir if state_dir.is_absolute() else None


def _is_relay_owned_bin_dir(entry: str, *, state_dir: Path) -> bool:
    path = Path(entry) if entry else None
    return bool(
        path
        and path.is_absolute()
        and path.name == "bin"
        and path.parent.parent == state_dir
    )


def _strip_relay_owned_path_entries(path_value: str, env: Mapping[str, str]) -> str:
    state_dir = _relay_owned_state_dir(env)
    if state_dir is None:
        return path_value
    kept = [
        entry
        for entry in path_value.split(os.pathsep)
        if not _is_relay_owned_bin_dir(entry, state_dir=state_dir)
    ]
    return os.pathsep.join(kept)


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
    if "PATH" in env:
        env["PATH"] = _strip_relay_owned_path_entries(env["PATH"], env)
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


__all__ = ["native_session_environment"]
