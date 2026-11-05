"""Native title readers observe names, never first prompts or message bodies."""

import json
import sqlite3
from types import SimpleNamespace

from yoke_contracts.hook_runner.client_facts import HARNESS_TITLE_KEY, read_client_fact
from yoke_harness.hooks import client_session_title as titles


def observation(executor, **payload):
    return SimpleNamespace(
        event_name="UserPromptSubmit",
        executor=executor,
        payload={"session_id": "chat", **payload},
    )


def database(path, script, parameters=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        if parameters:
            conn.execute(script, parameters)
        else:
            conn.executescript(script)


def test_claude_rename_and_forward_scan_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(
        titles.machine_config, "effective_temp_root", lambda: str(tmp_path / "cache")
    )
    transcript = tmp_path / "chat.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "[PILLS]"})
        + "\n"
        + " " * 70000
    )
    obs = observation("claude-code", transcript_path=str(transcript))
    assert read_client_fact(titles.title_fact(obs), HARNESS_TITLE_KEY) == "[PILLS]"
    assert titles.title_fact(obs, transcript_tail="") == {}
    with transcript.open("a") as stream:
        stream.write(
            "\n" + json.dumps({"type": "custom-title", "customTitle": "Renamed"}) + "\n"
        )
    assert read_client_fact(titles.title_fact(obs), HARNESS_TITLE_KEY) == "Renamed"
    assert titles.title_fact(obs) == {}


def test_stop_uses_supplied_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(
        titles.machine_config, "effective_temp_root", lambda: str(tmp_path / "cache")
    )
    transcript = tmp_path / "chat.jsonl"
    transcript.write_text("")
    obs = observation("claude-code", transcript_path=str(transcript))
    obs.event_name = "Stop"
    tail = json.dumps({"type": "custom-title", "customTitle": "Tail title"})
    assert (
        read_client_fact(
            titles.title_fact(obs, transcript_tail=tail), HARNESS_TITLE_KEY
        )
        == "Tail title"
    )


def test_codex_uses_latest_thread_name_then_database_name(tmp_path):
    index = tmp_path / "session_index.jsonl"
    index.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"id": "chat", "thread_name": "Old"},
                {"id": "unrelated", "thread_name": "Other"},
                {"id": "chat", "thread_name": "Current"},
            ]
        )
    )
    assert titles.codex_title("chat", tmp_path) == "Current"
    database(
        tmp_path / "state_5.sqlite",
        "CREATE TABLE threads(id TEXT PRIMARY KEY,name TEXT,title TEXT);",
    )
    database(
        tmp_path / "state_5.sqlite",
        "INSERT INTO threads VALUES (?,?,?)",
        ("db-chat", "Database name", "Secret first prompt"),
    )
    assert titles.codex_title("db-chat", tmp_path) == "Database name"
    assert titles.codex_title("missing", tmp_path) is None


def test_codex_home_and_prompt_rename(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(
        titles.machine_config, "effective_temp_root", lambda: str(tmp_path / "cache")
    )
    index = tmp_path / "session_index.jsonl"
    index.write_text(json.dumps({"id": "chat", "thread_name": "First"}))
    obs = observation("codex", native_thread_id="wrong-id")
    assert read_client_fact(titles.title_fact(obs), HARNESS_TITLE_KEY) == "First"
    index.write_text(json.dumps({"id": "chat", "thread_name": "Second"}))
    assert read_client_fact(titles.title_fact(obs), HARNESS_TITLE_KEY) == "Second"


def test_cursor_desktop_and_cli_names(tmp_path):
    desktop = (
        tmp_path / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
    )
    database(desktop, "CREATE TABLE cursorDiskKV(key TEXT PRIMARY KEY,value TEXT);")
    database(
        desktop,
        "INSERT INTO cursorDiskKV VALUES (?,?)",
        ("composerData:desktop", json.dumps({"name": "Desktop title"})),
    )
    assert titles.cursor_title("desktop", tmp_path) == "Desktop title"
    cli = tmp_path / ".cursor/chats/project/chat/store.db"
    database(cli, "CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);")
    database(
        cli,
        "INSERT INTO meta VALUES (?,?)",
        ("0", json.dumps({"name": "CLI title"}).encode().hex()),
    )
    assert titles.cursor_title("chat", tmp_path) == "CLI title"
    database(
        cli,
        "UPDATE meta SET value=?",
        (json.dumps({"name": "New Agent"}).encode().hex(),),
    )
    assert titles.cursor_title("chat", tmp_path) is None
    assert titles.cursor_title("headless", tmp_path) is None
