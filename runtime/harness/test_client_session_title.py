"""Native title readers observe names, never first prompts or message bodies."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

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
    assert (
        read_client_fact(titles.title_fact(obs, transcript_tail=""), HARNESS_TITLE_KEY)
        == "[PILLS]"
    )
    titles.confirm_title(obs.payload, obs.executor, {"value": "[PILLS]"})
    assert titles.title_fact(obs, transcript_tail="") == {}
    with transcript.open("a") as stream:
        stream.write(
            "\n" + json.dumps({"type": "custom-title", "customTitle": "Renamed"}) + "\n"
        )
    assert read_client_fact(titles.title_fact(obs), HARNESS_TITLE_KEY) == "Renamed"
    titles.confirm_title(obs.payload, obs.executor, {"value": "Renamed"})
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


def test_cursor_desktop_and_cli_names(tmp_path, monkeypatch):
    monkeypatch.setattr(titles.sys, "platform", "darwin")
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


def test_stop_reuses_tail_and_isolates_title_failure(tmp_path, monkeypatch):
    from yoke_contracts import turn_end_evidence
    from yoke_harness.hooks import client_facts

    reads = []

    def tail(path):
        reads.append(path)
        return json.dumps(
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": "Finished."},
            }
        )

    monkeypatch.setattr(turn_end_evidence, "read_transcript_tail", tail)

    def failed_title(obs, **kwargs):
        assert kwargs["transcript_tail"] is not None
        raise OSError("native title store unavailable")

    monkeypatch.setattr(client_facts, "title_fact", failed_title)
    facts = client_facts.collect_client_facts(
        "Stop",
        {"session_id": "chat", "transcript_path": str(tmp_path / "chat.jsonl")},
        "claude-code",
        [
            "yoke_core.hooks.session_title",
            "yoke_core.domain.turn_end_promised_work_gate",
        ],
    )
    assert reads == [str(tmp_path / "chat.jsonl")]
    assert HARNESS_TITLE_KEY not in facts
    assert facts[turn_end_evidence.PAYLOAD_KEY]["available"] is True


@pytest.mark.parametrize(
    "platform,key",
    [
        ("linux", None),
        ("linux", "XDG_CONFIG_HOME"),
        ("win32", None),
        ("win32", "APPDATA"),
    ],
)
def test_cursor_desktop_uses_native_config_root(tmp_path, monkeypatch, platform, key):
    monkeypatch.setattr(titles.sys, "platform", platform)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    root = tmp_path / (".config" if platform == "linux" else "AppData/Roaming")
    if key:
        root = tmp_path / "custom-config"
        monkeypatch.setenv(key, str(root))
    desktop = root / "Cursor/User/globalStorage/state.vscdb"
    database(desktop, "CREATE TABLE cursorDiskKV(key TEXT PRIMARY KEY,value TEXT);")
    database(
        desktop,
        "INSERT INTO cursorDiskKV VALUES (?,?)",
        ("composerData:desktop", json.dumps({"name": "Native title"})),
    )
    assert titles.cursor_title("desktop", tmp_path) == "Native title"


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "Stop"])
@pytest.mark.parametrize("executor", ["claude-desktop", "codex-cli", "cursor-desktop"])
def test_surface_title_reaches_relay_and_waits_for_confirmation(
    tmp_path, monkeypatch, event, executor
):
    from yoke_harness.hooks import client_facts

    monkeypatch.setattr(
        titles.machine_config, "effective_temp_root", lambda: str(tmp_path / "cache")
    )
    monkeypatch.setattr(titles.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setattr(titles.sys, "platform", "darwin")
    transcript = tmp_path / "chat.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "Native name"})
    )
    index = tmp_path / ".codex/session_index.jsonl"
    index.parent.mkdir()
    index.write_text(json.dumps({"id": "chat", "thread_name": "Native name"}))
    desktop = (
        tmp_path / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
    )
    database(desktop, "CREATE TABLE cursorDiskKV(key TEXT PRIMARY KEY,value TEXT);")
    database(
        desktop,
        "INSERT INTO cursorDiskKV VALUES (?,?)",
        ("composerData:chat", json.dumps({"name": "Native name"})),
    )
    payload = {"session_id": "chat", "transcript_path": str(transcript)}
    chain = client_facts.event_chain(event, payload)

    def collect():
        return client_facts.collect_client_facts(event, payload, executor, chain)

    for _ in range(2):
        assert read_client_fact(collect(), HARNESS_TITLE_KEY) == "Native name"
    titles.confirm_title(payload, executor, {"value": "Native name"})
    assert HARNESS_TITLE_KEY not in collect()
