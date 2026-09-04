"""Read the model a Cursor conversation actually executed under.

Cursor's hook payload names a bare model id (``grok-4.6``) that drops the
effort tier, and a launch's requested model is a request rather than a
fact — cursor-agent refuses a variant outside its own bracket catalog and
keeps the machine default instead, so a session launched at one variant can
run at another. The variant that actually served the turn is written per
conversation by Cursor itself:

    ~/.cursor/chats/<md5(workspace)>/<conversation-id>/store.db
    blobs.data contains {"providerOptions":{"cursor":{"modelName":"..."}}}

That value is the record. Blobs are appended per request, so the newest
one naming a model is the variant currently serving the conversation; a
model changed mid-conversation therefore reads as its current value rather
than its first. The workspace directory is keyed by a digest of the
conversation's cwd, which a hook process cannot always reconstruct (the
same conversation is reachable from a lane and its main checkout), so the
conversation id is matched across workspace directories instead.

Machine-local by construction: only a process on the machine running
cursor-agent can see this file, which is why the read lives on the harness
side and travels to the control plane as an ordinary observed model.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping


CURSOR_CHATS_DIR = Path("~/.cursor/chats")

# The literal wire shape Cursor writes into its conversation blobs. Anchored
# on the whole ``providerOptions`` prefix so a bare ``modelName`` mentioned
# in transcript text — an agent quoting this very format, which happens —
# cannot be mistaken for the conversation's own model.
_MODEL_NAME = re.compile(rb'"providerOptions":\{"cursor":\{"modelName":"([^"]{1,120})"')


def conversation_store_paths(
    conversation_id: str,
    *,
    chats_dir: Path | None = None,
) -> list[Path]:
    """Return every ``store.db`` Cursor holds for ``conversation_id``."""
    if not _safe_conversation_id(conversation_id):
        return []
    root = (chats_dir or CURSOR_CHATS_DIR).expanduser()
    try:
        workspaces = sorted(root.iterdir())
    except OSError:
        return []
    found: list[Path] = []
    for workspace in workspaces:
        store = workspace / conversation_id / "store.db"
        if store.is_file():
            found.append(store)
    return found


def executed_model(
    conversation_id: str,
    *,
    chats_dir: Path | None = None,
) -> str:
    """Return the model this conversation last executed under, or ``""``.

    Empty means the fact is not available yet — a conversation whose first
    request has not been composed has no naming blob — never that the
    conversation ran the machine default. A caller that cannot read the fact
    records the session model as unknown rather than substituting a request.
    """
    for store in conversation_store_paths(conversation_id, chats_dir=chats_dir):
        model = _newest_model_in_store(store)
        if model:
            return model
    return ""


def executed_model_for_payload(
    payload: Mapping[str, Any],
    *,
    chats_dir: Path | None = None,
) -> str:
    """Return the executed model for the conversation a hook payload names.

    A subagent's hook payload names the subagent's own conversation, which
    Cursor does not give a top-level store, so the container the transcript
    path identifies is tried first — that is the conversation Yoke registers
    and the one whose store holds the model. The payload's own ids follow
    for a top-level event, where they are the container.
    """
    from yoke_contracts.cursor_session_map import (
        container_session_id_from_evidence,
    )

    try:
        candidates = [container_session_id_from_evidence(payload)]
    except Exception:
        candidates = []
    candidates += [payload.get("conversation_id"), payload.get("session_id")]
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str) or candidate in seen:
            continue
        seen.add(candidate)
        model = executed_model(candidate, chats_dir=chats_dir)
        if model:
            return model
    return ""


def _safe_conversation_id(value: str) -> bool:
    """Reject anything that could escape the chats directory."""
    text = str(value or "").strip()
    if not text or len(text) > 128:
        return False
    if os.sep in text or "/" in text or text in {".", ".."}:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+", text))


def _newest_model_in_store(store: Path) -> str:
    try:
        connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    except sqlite3.Error:
        return ""
    try:
        # Newest first: the model is written on every request, so the
        # answer is normally in the first blob or two and the scan stops
        # there. A store naming no model at all drains fully, which on the
        # largest conversation measured here is 86ms of local file read.
        rows = connection.execute("SELECT data FROM blobs ORDER BY rowid DESC")
        for (data,) in rows:
            if not isinstance(data, (bytes, bytearray)):
                continue
            match = None
            for match in _MODEL_NAME.finditer(bytes(data)):
                pass
            if match is not None:
                return match.group(1).decode("utf-8", "replace").strip()
    except sqlite3.Error:
        return ""
    finally:
        connection.close()
    return ""


__all__ = [
    "CURSOR_CHATS_DIR",
    "conversation_store_paths",
    "executed_model",
    "executed_model_for_payload",
]
