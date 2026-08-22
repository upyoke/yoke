"""Canonical, dependency-free ambient session-identity resolution.

Single owner of the chain every Yoke surface uses to answer "which
harness session is this process running under?":

1. **Env chain (fast path):** ``YOKE_SESSION_ID`` -> ``CLAUDE_SESSION_ID``
   -> ``CODEX_SESSION_ID`` -> ``CODEX_THREAD_ID``.
2. **Process-anchor ancestry walk:** a hook-written registry under
   ``<machine-home>/session-anchors/`` maps the per-session harness agent
   pid to its session id, so any shell the harness spawns self-identifies
   by walking its parent chain against the registry — even when no env
   stamp was delivered.
3. **Conversation mapping:** a harness that neither stamps step 1 nor can
   be anchored resolves through the pairing its own hooks record
   (:mod:`yoke_contracts.cursor_session_map`).

Pure standard library; takes ``anchors_dir`` as an argument so BOTH sides
of the contract share one body: the engine core (server / in-process
dispatch) via the thin ``yoke_core.domain`` re-export shims, and the
product CLI client, which depends only on ``yoke-contracts`` and MUST
resolve identity client-side because, on the https transport, the remote
server cannot inspect the caller's process tree. Keeping one
implementation here is what prevents the resolver drift that let an
env-only client copy silently omit the ancestry fallback.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union

from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    resolve_mapped_session_id,
)
from yoke_contracts.process_ancestry import (
    ProcessAnchor,
    anchor_candidate_pids,
    find_nearest_harness_anchor,
    process_start_time,
)
from yoke_contracts.session_anchor_contention import (
    ContenderIsLive,
    resolve_tenancy,
    writer_breadcrumb,
)


# ---------------------------------------------------------------------------
# Env chain
# ---------------------------------------------------------------------------

# Codex exports the *parent* thread as ``CODEX_SESSION_ID`` in every
# process it starts and the subagent's own as ``CODEX_THREAD_ID``; parent
# first, because a child-resolved thread names an unregistered session.
AMBIENT_ENV_VARS: Tuple[str, ...] = (
    "YOKE_SESSION_ID",
    "CLAUDE_SESSION_ID",
    "CODEX_SESSION_ID",
    "CODEX_THREAD_ID",
)

# One denial sentence for every surface that requires a session and found
# none. Names the infrastructure-gap framing and the operator-debug
# override; deliberately does NOT teach env-var self-bootstrap.
AMBIENT_RESOLUTION_FAILED = (
    "ambient session identity could not be resolved (env chain, then the "
    "hook-written process-anchor registry, then cursor-session-map) — this "
    "is a Yoke infrastructure gap, not something to work around; file a "
    "field-note if you can, otherwise report it to the operator. "
    "Operator-debug override: --session-id."
)

ANCHORS_DIR_NAME = "session-anchors"

# A dispatched subagent shares its parent's session id, so the role is the
# only thing distinguishing who inside that session is acting. Harness
# adapters stamp it on the subagent's commands; only the calling process
# can observe it, since the https transport puts the server on the far
# side of the process tree.
ACTOR_ROLE_ENV_VAR = "YOKE_HOOK_AGENT_TYPE"

_AnchorsDir = Union[str, "os.PathLike[str]"]


def resolve_env_session_id(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return the first non-empty session id from the canonical env chain."""
    source = os.environ if env is None else env
    for name in AMBIENT_ENV_VARS:
        value = source.get(name)
        if value:
            return value
    return None


def resolve_actor_role(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return the dispatched subagent role for this process, if any.

    ``None`` in a top-level session, which has no role beyond its executor.
    """
    source = os.environ if env is None else env
    return (source.get(ACTOR_ROLE_ENV_VAR) or "").strip() or None


# ---------------------------------------------------------------------------
# Anchor registry (read / write / prune) — one small JSON file per anchor pid
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _dump_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def record_session_anchor(
    session_id: str,
    anchors_dir: _AnchorsDir,
    *,
    transcript_path: str = "",
    pid: Optional[int] = None,
    anchor: Optional[ProcessAnchor] = None,
    contender_is_live: Optional["ContenderIsLive"] = None,
) -> Optional[Dict[str, Any]]:
    """Record the calling process's nearest harness ancestor for ``session_id``.

    Returns the written record, or ``None`` when no harness ancestor exists
    (e.g. an operator terminal) or the write failed. Never raises — anchor
    recording is a best-effort side channel and must not break
    registration. ``anchor`` injects a resolved ancestor for tests.

    A pid recorded against a *different* live session cannot identify either
    session, so the record becomes a contention marker that makes ancestry
    resolution refuse the pid — but a marker, not a latch: tenancy is
    re-decided on every write (:mod:`yoke_contracts.session_anchor_contention`),
    so a contender that has ended, or that a clean record anchors to another
    live process, drops out and the sole remaining tenant gets the pid back.
    ``contender_is_live`` supplies the sessions-table liveness probe; without
    it, contenders only clear via the anchored-elsewhere evidence.
    """
    if not session_id:
        return None
    try:
        resolved = (
            anchor
            if anchor is not None
            else find_nearest_harness_anchor(pid)
        )
        if resolved is None:
            return None
        directory = Path(anchors_dir)
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / f"{resolved.pid}.json"
        existing = _load_json(final) if final.is_file() else None
        if existing and existing.get("anchor_start_time") != resolved.start_time:
            existing = None  # reused pid: the recorded process is gone
        decision = resolve_tenancy(
            existing,
            session_id,
            anchors_dir=directory,
            this_pid=resolved.pid,
            load_record=_load_json,
            start_time_of=process_start_time,
            contender_is_live=contender_is_live,
        )
        record: Dict[str, Any] = {
            "session_id": decision.tenant_session_id,
            "transcript_path": "" if decision.contended else (transcript_path or ""),
            "anchor_pid": resolved.pid,
            "anchor_start_time": resolved.start_time,
            "anchor_process_name": resolved.process_name,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        if decision.contended:
            record["shared_by_multiple_sessions"] = True
            record["contending_session_ids"] = list(
                decision.contending_session_ids
            )
            record.update(writer_breadcrumb())
        tmp = directory / f".{resolved.pid}.json.tmp.{os.getpid()}"
        _dump_json(tmp, record)
        os.replace(tmp, final)
    except (OSError, ValueError):
        return None
    return record


def resolve_session_from_ancestry(
    anchors_dir: _AnchorsDir,
    pid: Optional[int] = None,
    *,
    start_time_of: Optional[Callable[[int], Optional[str]]] = None,
    parents: Optional[Dict[int, int]] = None,
    name_of: Optional[Callable[[int], Optional[str]]] = None,
) -> Optional[str]:
    """Resolve the ambient session id by walking this process's ancestry.

    Walks :func:`anchor_candidate_pids`, so the chain ends at a
    multiplexed harness host exactly as the write side's does, and for the
    reason documented there. For each candidate pid (nearest first) holding a registry record, the
    record is trusted only when the ancestor's live start time equals the
    recorded one — a reused pid fails the comparison and the stale record
    is pruned. A record marked as shared by multiple sessions stops the
    walk with ``None``: the pid cannot identify one session, and no
    ancestor above it is less shared. Returns ``None`` when no live anchor
    covers this process. Never raises. ``start_time_of`` / ``parents`` /
    ``name_of`` inject process-table lookups for tests.
    """
    try:
        directory = Path(anchors_dir)
        if not directory.is_dir():
            return None
        # Cheap emptiness probe before any subprocess: an empty registry
        # (fresh machine, hermetic test home) resolves to None for free.
        if not any(directory.glob("*.json")):
            return None
        resolve_start = (
            process_start_time if start_time_of is None else start_time_of
        )
        for ancestor in anchor_candidate_pids(
            pid, parents=parents, name_of=name_of,
        ):
            path = directory / f"{ancestor}.json"
            if not path.is_file():
                continue
            record = _load_json(path)
            if record is None:
                _remove_quietly(path)
                continue
            recorded_start = record.get("anchor_start_time")
            if not recorded_start or resolve_start(ancestor) != recorded_start:
                _remove_quietly(path)
                continue
            if record.get("shared_by_multiple_sessions"):
                return None
            session_id = record.get("session_id")
            if isinstance(session_id, str) and session_id:
                return session_id
            _remove_quietly(path)
    except Exception:  # noqa: BLE001 — ambient resolution must never raise
        return None
    return None


def prune_stale_anchors(
    anchors_dir: _AnchorsDir,
    *,
    start_time_of: Optional[Callable[[int], Optional[str]]] = None,
) -> int:
    """Best-effort sweep removing records whose pid died or was reused.

    Operator/maintenance utility — the resolution path already ignores and
    prunes stale records inline on every read, so a missed sweep is
    harmless. Returns the number of records removed; never raises.
    """
    removed = 0
    try:
        directory = Path(anchors_dir)
        if not directory.is_dir():
            return 0
        resolve_start = (
            process_start_time if start_time_of is None else start_time_of
        )
        for path in directory.glob("*.json"):
            try:
                pid = int(path.stem)
            except ValueError:
                continue
            record = _load_json(path)
            recorded_start = (record or {}).get("anchor_start_time")
            if record is None or not recorded_start:
                _remove_quietly(path)
                removed += 1
                continue
            if resolve_start(pid) != recorded_start:
                _remove_quietly(path)
                removed += 1
    except Exception:  # noqa: BLE001 — pruning must never fail the caller
        return removed
    return removed


# ---------------------------------------------------------------------------
# The unified ambient chain
# ---------------------------------------------------------------------------

def resolve_ambient_session_id(
    anchors_dir: _AnchorsDir,
    env: Optional[Mapping[str, str]] = None,
    *,
    cursor_map_dir: Optional[_AnchorsDir] = None,
) -> Optional[str]:
    """Resolve ambient session identity: env chain, ancestry, hook mapping.

    Returns ``None`` when no source yields an id. Never raises. Each
    layer resolves its own machine home and passes the two directories
    below it; omitting ``cursor_map_dir`` skips the Cursor lane.

    Ancestry precedes the mapping deliberately: a per-session harness
    nested inside a Cursor agent inherits ``CURSOR_CONVERSATION_ID``
    through the environment, and its own anchor — reached before the
    shared Cursor host — is the truthful answer.
    """
    value = resolve_env_session_id(env)
    if value:
        return value
    value = resolve_session_from_ancestry(anchors_dir)
    if value:
        return value
    if cursor_map_dir is None:
        return None
    return resolve_mapped_session_id(cursor_map_dir, env)


__all__ = [
    "ACTOR_ROLE_ENV_VAR",
    "AMBIENT_ENV_VARS",
    "AMBIENT_RESOLUTION_FAILED",
    "ANCHORS_DIR_NAME",
    "CURSOR_SESSION_MAP_DIR_NAME",
    "ContenderIsLive",
    "ProcessAnchor",
    "prune_stale_anchors",
    "record_session_anchor",
    "resolve_actor_role",
    "resolve_ambient_session_id",
    "resolve_env_session_id",
    "resolve_session_from_ancestry",
]
