"""Which harness family a process belongs to, and how that family names it.

A harness stamps its session id into every process it starts, and every
process those start in turn inherits it — including another harness. A
``codex exec`` run launched from a Claude session's shell therefore
carries ``CLAUDE_CODE_SESSION_ID`` naming a session it is not part of,
and a chain that reads the environment in one fixed order answers with
the launching session. Observed live: a nested Codex child and a nested
Cursor child each resolved to the parent Claude session and would have
acted with its authority, while their own registrations sat unused.

The environment cannot settle this — both variables are present and
neither records which process exported it. The process tree can: the
nearest harness ancestor is the harness this process actually runs
under, and no descendant can inherit or stale that fact. This module
answers that question and owns the per-family identity vocabulary that
:mod:`yoke_contracts.session_identity` composes into the ambient chain.

Pure standard library, so both sides of the identity contract share one
body: the engine core through its ``yoke_core.domain`` re-export shims,
and the product CLI client, which must resolve identity locally because
an https server cannot inspect the caller's process tree.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Mapping, Optional, Tuple

from yoke_contracts.executor_labels import (
    CANONICAL_HARNESS_IDS,
    canonical_harness_id,
)
from yoke_contracts.process_ancestry import (
    HARNESS_PROCESS_BASENAMES,
    MULTIPLEXED_PROCESS_BASENAMES,
    ancestor_pids,
    process_table,
)


# The family vocabulary is closed and ordered by CANONICAL_HARNESS_IDS.
# Binding the three names here keeps this module from restating them, and
# a fourth family fails loudly at import rather than quietly missing a
# branch below.
CLAUDE_FAMILY, CODEX_FAMILY, CURSOR_FAMILY = CANONICAL_HARNESS_IDS

# Yoke's own stamp sits outside the family vocabulary: it is what an
# explicit ``--session-id`` propagates for one invocation, so it is a
# deliberate operator override rather than something a harness exported,
# and it outranks every ambient channel below.
YOKE_SESSION_ENV_VAR = "YOKE_SESSION_ID"

HARNESS_FAMILY_ENV_VARS: Mapping[str, Tuple[str, ...]] = {
    CLAUDE_FAMILY: ("CLAUDE_CODE_SESSION_ID",),
    # Parent before child: ``CODEX_SESSION_ID`` holds the parent thread in
    # every process Codex starts and only the parent is registered, so a
    # subagent reading its own ``CODEX_THREAD_ID`` would name a session
    # that has no row.
    CODEX_FAMILY: ("CODEX_SESSION_ID", "CODEX_THREAD_ID"),
    # Cursor stamps no session id: one process hosts every conversation,
    # and identity arrives through the hook-written conversation map
    # (:mod:`yoke_contracts.cursor_session_map`) instead.
    CURSOR_FAMILY: (),
}

SESSION_ID_ENV_FAMILIES: Tuple[str, ...] = (CLAUDE_FAMILY, CODEX_FAMILY)
"""Families whose variables carry a session id, in ambient-chain order."""

# Claude Code stamps ``CLAUDE_CODE_SESSION_ID`` into every subprocess,
# background agent and interactive alike, and for a launched worker it is
# the only per-conversation identity that arrives: those shells descend
# from pooled daemon processes, so an anchor on the reused pid is claimed
# by each worker in turn and names none.
AMBIENT_ENV_VARS: Tuple[str, ...] = (
    YOKE_SESSION_ENV_VAR,
    *(
        name
        for family in SESSION_ID_ENV_FAMILIES
        for name in HARNESS_FAMILY_ENV_VARS[family]
    ),
)

_HARNESS_BASENAMES = HARNESS_PROCESS_BASENAMES | MULTIPLEXED_PROCESS_BASENAMES

# A process's ancestry is fixed for its whole life, so the walk runs once
# per process rather than once per identity resolution — which matters
# because event emission resolves identity repeatedly and each walk costs
# a process-table read.
_MISSING = object()
_nearest_family_by_pid: Dict[int, Optional[str]] = {}


def resolve_env_session_id(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return the first non-empty session id from the canonical env chain.

    Family-blind by design: this is the fallback for a process with no
    harness ancestor to scope it, where an inherited variable is the best
    evidence available.
    """
    source = os.environ if env is None else env
    for name in AMBIENT_ENV_VARS:
        value = source.get(name)
        if value:
            return value
    return None


def family_env_session_id(
    family: Optional[str],
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return the session id ``family`` itself stamped into this process."""
    source = os.environ if env is None else env
    for name in HARNESS_FAMILY_ENV_VARS.get(family or "", ()):
        value = (source.get(name) or "").strip()
        if value:
            return value
    return None


def harness_family_of_process_name(name: Optional[str]) -> Optional[str]:
    """Return the harness family running as ``name``, or ``None``.

    Classifies the per-session harness binaries and the multiplexed hosts
    alike, because a shared host still says which harness its descendants
    belong to even though it can never anchor one session. Any other
    process name is not a harness and returns ``None``.
    """
    basename = os.path.basename((name or "").strip()).lower()
    if basename not in _HARNESS_BASENAMES:
        return None
    try:
        # Pooled Claude hosts announce their role in the process title
        # ("claude bg-spare"), which reads as a family suffix once the
        # space is spelled the way every other surface value is.
        return canonical_harness_id(basename.replace(" ", "-"))
    except ValueError:
        return None


def _walk_for_family(
    pid: Optional[int],
    parents: Optional[Dict[int, int]],
    name_of: Optional[Callable[[int], Optional[str]]],
) -> Optional[str]:
    """Nearest harness ancestor's family from one process-table view."""
    resolve_name = name_of
    if resolve_name is None:
        if parents is not None:
            # A tree with no names describes no harness: reading live
            # names against an injected tree would mix two process
            # worlds and classify by coincidence.
            return None
        table = process_table()
        parents = {ancestor: entry[0] for ancestor, entry in table.items()}
        resolve_name = {
            ancestor: entry[1] for ancestor, entry in table.items()
        }.get
    for ancestor in ancestor_pids(pid, parents=parents):
        family = harness_family_of_process_name(resolve_name(ancestor))
        if family:
            return family
    return None


def nearest_harness_family(
    pid: Optional[int] = None,
    *,
    parents: Optional[Dict[int, int]] = None,
    name_of: Optional[Callable[[int], Optional[str]]] = None,
) -> Optional[str]:
    """Return the family of the innermost harness ancestor of this process.

    ``None`` when no ancestor is a harness at all — an operator terminal,
    CI, or a process reparented after its harness exited — which is
    exactly where an inherited variable is the best evidence available
    and the family-blind chain stays in charge.

    Unlike the anchor walk this one passes *through* a multiplexed host,
    because the question here is which harness owns the process, not
    which pid can name one session. Never raises. ``parents`` /
    ``name_of`` inject a process table for tests and, as in the anchor
    walk, describe one tree together.
    """
    injected = pid is not None or parents is not None or name_of is not None
    if not injected:
        cached = _nearest_family_by_pid.get(os.getpid(), _MISSING)
        if cached is not _MISSING:
            return cached  # type: ignore[return-value]
    try:
        family = _walk_for_family(pid, parents, name_of)
    except Exception:  # noqa: BLE001 — identity resolution must never raise
        return None
    if not injected:
        _nearest_family_by_pid[os.getpid()] = family
    return family


__all__ = [
    "AMBIENT_ENV_VARS",
    "CLAUDE_FAMILY",
    "CODEX_FAMILY",
    "CURSOR_FAMILY",
    "HARNESS_FAMILY_ENV_VARS",
    "SESSION_ID_ENV_FAMILIES",
    "YOKE_SESSION_ENV_VAR",
    "family_env_session_id",
    "harness_family_of_process_name",
    "nearest_harness_family",
    "resolve_env_session_id",
]
