"""Session lifecycle duties that belong to the machine running the harness.

``yoke_core.hooks.session_dispatch`` is a ``CLIENT`` policy
(:mod:`yoke_contracts.hook_runner.policy_home`). Two of its SessionStart
duties touch only this machine, and this module is their one
implementation, used by the relay client and by the in-process dispatch:

- fast-forward the project's default-branch checkout to its remote, never
  touching local commits or uncommitted work;
- persist ``YOKE_SESSION_ID`` into Claude's ``CLAUDE_ENV_FILE`` so every
  later Bash call in the session inherits its identity.

The control-plane duties run where the session row lives: an in-process
local universe runs them in ``session_dispatch``; over HTTPS the authority
runs registration (relay ensure-register), the resume block
(``yoke_core.hooks.session_resume_block``) and end-of-session cleanup
(``yoke_core.hooks.remote_lifecycle``). The Codex start marker that tells
``session_dispatch`` a resumed thread from a new one guards those
control-plane duties, so it lives with them; the relay records the Codex
runtime cache itself (``relay_identity_guard.capture_codex_session``).

Every duty is best effort and never fails the hook; an update that could not
run is written to stderr as ``YOKE_MAIN_CHECKOUT_NOT_SYNCED`` with the
recovery the freshness check names.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Mapping

from yoke_cli.config.repo_upstream_freshness import refresh_base_branch
from yoke_contracts.hook_runner.chain_registry import SESSION_START_EVENT
from yoke_contracts.hook_runner.project_scope import resolve_hook_project_scope
from yoke_contracts.machine_config.checkout import main_checkout
from yoke_contracts.session_identity import AMBIENT_ENV_VARS

from yoke_harness.hooks.identity_runtime import is_codex, is_cursor
from yoke_harness.hooks.local_policy_common import NOOP, PolicyResult, cwd_from_payload

NOT_SYNCED_MARKER = "YOKE_MAIN_CHECKOUT_NOT_SYNCED"
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def sync_session_main_checkout(repo_root: str) -> str:
    """Bring the default branch of *repo_root* current; return any advisory."""
    freshness = refresh_base_branch(repo_root, "", use_cache=False)
    if not freshness.needs_attention:
        return ""
    advisory = f"main checkout not fast-forwarded: {freshness.note}"
    sys.stderr.write(f"WARNING: {NOT_SYNCED_MARKER}: {advisory}\n")
    return advisory


def env_file_session_id(payload: Mapping[str, object]) -> str:
    """Resolve the session id SessionStart persists into the env file."""
    for env_var in AMBIENT_ENV_VARS:
        value = os.environ.get(env_var, "")
        if value:
            return value
    payload_sid = payload.get("session_id")
    if isinstance(payload_sid, str) and payload_sid:
        return payload_sid
    match = re.search(r"/session-env/([^/]+)/", os.environ.get("CLAUDE_ENV_FILE", ""))
    if match and _UUID_RE.fullmatch(match.group(1)):
        return match.group(1)
    return ""


def persist_session_env(payload: Mapping[str, object]) -> bool:
    """Append ``export YOKE_SESSION_ID=...`` to ``CLAUDE_ENV_FILE`` once."""
    session_id = env_file_session_id(payload)
    env_file = os.environ.get("CLAUDE_ENV_FILE", "")
    if not session_id or not env_file:
        return False
    try:
        if os.path.isfile(env_file):
            with open(env_file, encoding="utf-8") as handle:
                if "YOKE_SESSION_ID=" in handle.read():
                    return True
        with open(env_file, "a", encoding="utf-8") as handle:
            handle.write(f"export YOKE_SESSION_ID={session_id}\n")
        return True
    except OSError:
        return False


def session_lifecycle(event_name: str, payload: dict, executor: str) -> PolicyResult:
    """Run this machine's SessionStart duties for a Yoke project session."""
    if event_name != SESSION_START_EVENT:
        return PolicyResult(NOOP)
    if resolve_hook_project_scope(payload).project_id is None:
        return PolicyResult(NOOP)
    sync_session_main_checkout(str(main_checkout(cwd_from_payload(payload))))
    # Claude is the dispatch's default family: Codex and Cursor have no env file.
    if not is_codex(executor) and not is_cursor(executor):
        persist_session_env(payload)
    return PolicyResult(NOOP)


__all__ = [
    "NOT_SYNCED_MARKER",
    "env_file_session_id",
    "persist_session_env",
    "session_lifecycle",
    "sync_session_main_checkout",
]
