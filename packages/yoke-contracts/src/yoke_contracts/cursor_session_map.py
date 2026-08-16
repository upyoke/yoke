"""Map a Cursor conversation id to the session Yoke registered for it.

The third rung of the ambient-identity chain, for the one harness the
first two cannot reach. Cursor stamps no session-id environment variable
that :data:`~yoke_contracts.session_identity.AMBIENT_ENV_VARS` reads, and
one ``cursor-agent`` process hosts the main conversation plus every
subagent it dispatches — so the process-anchor registry correctly refuses
to anchor there, since a record keyed on that shared pid would resolve to
whichever sibling wrote last.

What a Cursor shell *does* carry is ``CURSOR_CONVERSATION_ID``: the
conversation that spawned it, which for a dispatched subagent is the
subagent's own id rather than the top-level session Yoke registered. A
bare conversation id is therefore not an identity — trusting it directly
would attribute subagent work to a session row that does not exist.

Cursor's hook processes see both ids at once: the payload names the
acting conversation, and the transcript path names the top-level
container. Each hook records that pair here, and a later shell resolves
its own conversation id through the recording — falling through
unresolved when no hook recorded it, rather than guessing.

Pure standard library and directory-injected, so every side shares one
body — the same split, and for the same reason, as
:mod:`yoke_contracts.session_identity`. The container resolution lives
here too, because the write happens in the *client* hook process (the
only side that can see this machine's transcript env and machine home)
while the harness adapter that shapes the same payload runs wherever the
hook chain is evaluated.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Union


CURSOR_SESSION_MAP_DIR_NAME = "cursor-session-map"

CURSOR_CONVERSATION_ENV_VAR = "CURSOR_CONVERSATION_ID"

# Prefer this env when present: it *should* name the top-level session's
# transcript even inside subagent hooks. When Cursor instead points it at
# the nested ``.../subagents/<child>.jsonl`` layout, ``transcript_session_id``
# recovers the parent from the path shape.
CURSOR_TRANSCRIPT_ENV_VAR = "CURSOR_TRANSCRIPT_PATH"

# A conversation outlives any single hook, so entries are kept for far
# longer than the model spool's seconds-long hand-off. The cap exists so a
# machine running Cursor for months does not accumulate a record per
# conversation forever, and so a recycled id can never resolve to an
# ancient session.
_STALE_AGE_S = 7 * 24 * 3600

# Conversation ids are uuid-shaped. Anything else is refused rather than
# sanitized: an id that cannot be a filename is an id we did not receive
# from Cursor, and quietly rewriting it would key the entry on something
# the reader will never ask for.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")

_MapDir = Union[str, "os.PathLike[str]"]


def transcript_session_id(transcript_path: str) -> str:
    """Return the container session id encoded in a Cursor transcript path.

    Top-level chats live at ``.../agent-transcripts/<id>/<id>.jsonl`` —
    the stem is the container. Task/subagent transcripts live at
    ``.../agent-transcripts/<parent>/subagents/<child>.jsonl``; the stem
    is the *child*, so resolving container from stem alone would mint a
    phantom ``harness_sessions`` row. When the path carries the nested
    ``agent-transcripts/<parent>/subagents/`` shape, ``<parent>`` is the
    container. Empty or malformed input returns empty output rather than
    guessing the child id.
    """
    if not transcript_path:
        return ""
    path = PurePosixPath(transcript_path.replace("\\", "/"))
    parts = path.parts
    try:
        transcripts_at = parts.index("agent-transcripts")
    except ValueError:
        if "subagents" in parts:
            return ""
        return path.stem
    # Nested: .../agent-transcripts/<parent>/subagents/<child>.jsonl
    if (
        transcripts_at + 2 < len(parts)
        and parts[transcripts_at + 2] == "subagents"
    ):
        parent = parts[transcripts_at + 1]
        return parent if parent else ""
    # Flat: .../agent-transcripts/<id>/<id>.jsonl
    return path.stem


def linked_worktree_lane_name(workspace_path: str) -> str:
    """Return the Yoke worktree lane name when ``workspace_path`` is under one.

    Recognizes ``.../.worktrees/<lane>`` and ``.../.claude/worktrees/<lane>``
    (and deeper paths under those roots). Empty when the path is not a
    linked worktree lane — including the main checkout itself.
    """
    if not workspace_path:
        return ""
    parts = PurePosixPath(workspace_path.replace("\\", "/")).parts
    for marker in (".worktrees", "worktrees"):
        try:
            idx = parts.index(marker)
        except ValueError:
            continue
        # Require the Yoke layout ``<repo>/.worktrees/<lane>`` (or Claude's
        # ``.claude/worktrees/<lane>``) rather than an arbitrary directory
        # named worktrees.
        if marker == "worktrees" and (
            idx == 0 or parts[idx - 1] != ".claude"
        ):
            continue
        if idx + 1 < len(parts) and parts[idx + 1]:
            return parts[idx + 1]
    return ""


def container_session_id_from_evidence(
    payload: Mapping[str, Any],
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve the container session from evidence that names it directly.

    Resolution order: the transcript-path env var (the top-level session's
    transcript, even inside a subagent hook, though unset for roughly a
    fresh session's first events), then ``parent_conversation_id`` on
    subagent lifecycle events, then the payload's own ``transcript_path``
    — which for a top-level event IS the container.

    Empty when none of the three is present: exactly the case where the
    event's own id may or may not be the container, and a wrong pairing is
    worse than a missing one.
    """
    source = os.environ if env is None else env
    resolved = transcript_session_id(source.get(CURSOR_TRANSCRIPT_ENV_VAR, "") or "")
    if resolved:
        return resolved
    parent = payload.get("parent_conversation_id")
    if isinstance(parent, str) and parent:
        return parent
    return transcript_session_id(str(payload.get("transcript_path", "") or ""))


def _entry_path(map_dir: _MapDir, conversation_id: str) -> Optional[Path]:
    if not conversation_id or not _SAFE_ID.match(conversation_id):
        return None
    return Path(map_dir) / f"{conversation_id}.json"


def record_conversation_session(
    conversation_id: str,
    session_id: str,
    map_dir: _MapDir,
) -> bool:
    """Record that ``conversation_id`` belongs to ``session_id``.

    Returns whether the pairing was written. Never raises — a hook must
    not fail on a bookkeeping file. Rewriting on every hook is deliberate:
    it keeps the entry's mtime fresh for the staleness cap, and it costs
    one small atomic write beside work the hook is already doing.
    """
    path = _entry_path(map_dir, conversation_id)
    if path is None or not session_id:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "session_id": session_id,
                "conversation_id": conversation_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=True,
        )
        tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        tmp.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, ValueError):
        return False
    return True


def recorded_session_id_for_conversation(
    map_dir: _MapDir, conversation_id: str,
) -> Optional[str]:
    """Return a live map entry's session id, or ``None`` when absent/stale."""
    path = _entry_path(map_dir, conversation_id)
    if path is None:
        return None
    try:
        if path.stat().st_mtime < time.time() - _STALE_AGE_S:
            path.unlink(missing_ok=True)
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    session_id = record.get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


def resolve_container_from_subagent_transcript_layout(
    conversation_id: str,
    *,
    projects_root: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> str:
    """Recover the parent session from Cursor's on-disk subagent transcript.

    Cursor Task subagents write under
    ``~/.cursor/projects/<proj>/agent-transcripts/<parent>/subagents/<child>.jsonl``
    even when hook processes omit ``CURSOR_TRANSCRIPT_PATH`` /
    ``parent_conversation_id``. A unique match is the container; zero or
    many matches refuse rather than guess. Never raises.
    """
    if not conversation_id or not _SAFE_ID.match(conversation_id):
        return ""
    root = Path(projects_root) if projects_root is not None else (
        Path.home() / ".cursor" / "projects"
    )
    try:
        matches = list(
            root.glob(
                f"*/agent-transcripts/*/subagents/{conversation_id}.jsonl"
            )
        )
    except OSError:
        return ""
    if len(matches) != 1:
        return ""
    # .../agent-transcripts/<parent>/subagents/<child>.jsonl
    parent = matches[0].parent.parent.name
    return parent if parent and parent != conversation_id else ""


def _resolve_unmapped_container(
    conversation_id: str,
    source: Mapping[str, str],
    *,
    projects_root: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> str:
    """Container for an unmapped conversation, or empty when unknown."""
    from_env = transcript_session_id(
        source.get(CURSOR_TRANSCRIPT_ENV_VAR, "") or ""
    )
    if from_env and from_env != conversation_id:
        return from_env
    return resolve_container_from_subagent_transcript_layout(
        conversation_id, projects_root=projects_root,
    )


def resolve_mapped_session_id(
    map_dir: _MapDir,
    env: Optional[Mapping[str, str]] = None,
    *,
    projects_root: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> Optional[str]:
    """Resolve this process's session from its Cursor conversation id.

    Prefers a hook-written map entry. When the map misses, recovers the
    parent from transcript env (nested ``subagents/`` layout) or from the
    on-disk Cursor transcript tree, then self-heals the map so later
    shells without those signals still resolve. ``None`` when the process
    carries no conversation id or no container evidence exists — never
    treat the bare conversation id as a registered session. Never raises.
    """
    source = os.environ if env is None else env
    conversation_id = (source.get(CURSOR_CONVERSATION_ENV_VAR) or "").strip()
    if not conversation_id or not _SAFE_ID.match(conversation_id):
        return None
    mapped = recorded_session_id_for_conversation(map_dir, conversation_id)
    if mapped:
        return mapped
    container = _resolve_unmapped_container(
        conversation_id, source, projects_root=projects_root,
    )
    if not container:
        return None
    record_conversation_session(conversation_id, container, map_dir)
    return container


def prune_stale_conversation_sessions(map_dir: _MapDir) -> int:
    """Drop recordings past the staleness cap. Returns how many were removed.

    Best-effort maintenance for the same session-start sweep that prunes
    the anchor registry; resolution already ages out the single entry it
    reads, so a missed sweep only leaves disk behind. Never raises.
    """
    removed = 0
    cutoff = time.time() - _STALE_AGE_S
    try:
        for entry in Path(map_dir).glob("*.json"):
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                entry.unlink(missing_ok=True)
            except OSError:
                continue
            removed += 1
    except OSError:
        return removed
    return removed


__all__ = [
    "CURSOR_CONVERSATION_ENV_VAR",
    "CURSOR_SESSION_MAP_DIR_NAME",
    "CURSOR_TRANSCRIPT_ENV_VAR",
    "container_session_id_from_evidence",
    "linked_worktree_lane_name",
    "prune_stale_conversation_sessions",
    "record_conversation_session",
    "recorded_session_id_for_conversation",
    "resolve_container_from_subagent_transcript_layout",
    "resolve_mapped_session_id",
    "transcript_session_id",
]
