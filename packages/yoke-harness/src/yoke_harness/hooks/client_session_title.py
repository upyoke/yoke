"""Read native chat names locally, without shipping chat content."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

from yoke_contracts.hook_runner.client_facts import HARNESS_TITLE_KEY, client_fact
from yoke_contracts.machine_config import runtime as machine_config


def _name(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _sqlite_cell(path: Path, sql: str, params: tuple):
    if not path.is_file():
        return None
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.05)
    try:
        row = conn.execute(sql, params).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def claude_title(lines):
    title = None
    for line in lines:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(record, dict) and record.get("type") == "custom-title":
            title = _name(record.get("customTitle")) or title
    return title


def codex_title(session_id: str, home: Path):
    title = None
    index = home / "session_index.jsonl"
    if index.is_file():
        with index.open() as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("id") == session_id:
                    title = _name(record.get("thread_name"))
    return title or _name(
        _sqlite_cell(
            home / "state_5.sqlite",
            "SELECT name FROM threads WHERE id=?",
            (session_id,),
        )
    )


def cursor_title(session_id: str, home: Path):
    if sys.platform == "darwin":
        config = home / "Library/Application Support"
    elif sys.platform == "win32":
        config = Path(os.environ.get("APPDATA") or home / "AppData/Roaming")
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    desktop = config / "Cursor/User/globalStorage/state.vscdb"
    raw = _sqlite_cell(
        desktop,
        "SELECT value FROM cursorDiskKV WHERE key=?",
        ("composerData:" + session_id,),
    )
    if raw:
        title = _name(json.loads(raw).get("name"))
        if title and title != "New Agent":
            return title
    for store in (home / ".cursor/chats").glob("*/" + session_id + "/store.db"):
        raw = _sqlite_cell(store, "SELECT value FROM meta WHERE key='0'", ())
        if raw:
            title = _name(
                json.loads(
                    bytes.fromhex(
                        raw.decode("ascii") if isinstance(raw, bytes) else raw
                    )
                ).get("name")
            )
            if title and title != "New Agent":
                return title
    return None


def title_fact(obs, *, transcript_tail: str | None = None):
    if obs.event_name not in {"Stop", "UserPromptSubmit"}:
        return {}
    session_id = str(obs.payload.get("session_id") or "")
    if (
        not session_id
        or any(char in session_id for char in "/\\*?[]")
        or obs.payload.get("isSidechain")
    ):
        return {}
    cache_path = _cache_path(obs.executor, session_id)
    try:
        cached = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cached = {}
    previous = cached.get("title")
    if obs.executor in {"claude", "claude-code"}:
        path = obs.payload.get("transcript_path")
        if not isinstance(path, str) or not Path(path).is_file():
            return {}
        if transcript_tail is None:
            with Path(path).open("rb") as stream:
                stream.seek(max(0, Path(path).stat().st_size - 65536))
                transcript_tail = stream.read(65536).decode("utf-8", errors="replace")
        title = claude_title(transcript_tail.splitlines())
        if title is None and previous is None and not cached.get("scanned"):
            with Path(path).open() as stream:
                title = claude_title(stream)
        title = title or previous
    elif obs.executor == "codex":
        title = codex_title(
            session_id, Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        )
    elif obs.executor == "cursor":
        title = cursor_title(session_id, Path.home())
    else:
        return {}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(json.dumps({**cached, "title": title, "scanned": True}))
    temporary.replace(cache_path)
    return (
        client_fact(HARNESS_TITLE_KEY, title)
        if title != cached.get("confirmed_title")
        else {}
    )


def _cache_path(executor, session_id):
    key = hashlib.sha256((executor + ":" + session_id).encode()).hexdigest()
    return (
        Path(machine_config.effective_temp_root())
        / "hook-chat-titles"
        / (key + ".json")
    )


def confirm_title(payload, executor, confirmed):
    """A failed or unconfirmed request must resend its observed title."""
    session_id = payload.get("session_id")
    if not session_id or not isinstance(confirmed, dict) or "value" not in confirmed:
        return
    cache = _cache_path(executor, session_id)
    try:
        cached = json.loads(cache.read_text())
        cached["confirmed_title"] = confirmed["value"]
        temporary = cache.with_suffix(".confirmed.tmp")
        temporary.write_text(json.dumps(cached))
        temporary.replace(cache)
    except (OSError, ValueError):
        return  # Without a marker the next hook safely resends.
