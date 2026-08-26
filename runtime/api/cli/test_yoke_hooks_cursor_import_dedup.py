"""Cursor deduplication for Claude-compatible project hook imports."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from yoke_contracts.hook_runner.config_owner import (
    CURSOR_LEGACY_LIFECYCLE_COMMAND_MARKER,
    CURSOR_LIFECYCLE_COMMAND_MARKER,
)
from yoke_cli.commands.adapters.hook_config_dedup import (
    should_skip_config_duplicate,
)
from yoke_cli.main import main as cli_main


def _write_cursor_owner(
    root: Path,
    native_events: str | tuple[str, ...],
    runner_event: str,
    *,
    lifecycle_marker: str = CURSOR_LIFECYCLE_COMMAND_MARKER,
    owner: str = "cursor-project",
) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    if isinstance(native_events, str):
        native_events = (native_events,)
    (cursor / "hooks.json").write_text(
        json.dumps({
            "version": 1,
            "hooks": {
                native_event: [{
                    "command": (
                        f"{lifecycle_marker}; "
                        f"env YOKE_HOOK_CONFIG_OWNER={owner} "
                        f"yoke hook evaluate {runner_event}"
                    ),
                    "timeout": 30,
                }]
                for native_event in native_events
            },
        }),
        encoding="utf-8",
    )


def test_cursor_imported_claude_hook_exits_before_transport(
    monkeypatch, tmp_path,
) -> None:
    _write_cursor_owner(tmp_path, "sessionStart", "SessionStart")
    stdin = io.StringIO(
        '{"session_id":"cursor-1","conversation_id":"cursor-1"}'
    )
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(
            AssertionError("deduplicated hook must not resolve transport")
        ),
    )

    assert cli_main(["hook", "evaluate", "SessionStart"]) == 0
    assert stdin.tell() > 0


def test_cursor_imported_claude_hook_runs_without_native_owner(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            '{"session_id":"cursor-legacy",'
            '"conversation_id":"cursor-legacy"}'
        ),
    )
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("transport reached")),
    )

    with pytest.raises(RuntimeError, match="transport reached"):
        cli_main(["hook", "evaluate", "SessionStart"])


@pytest.mark.parametrize(
    ("runner_event", "native_event", "native_runner_event"),
    (
        ("SessionStart", "sessionStart", "SessionStart"),
        ("SessionEnd", "sessionEnd", "SessionEnd"),
        ("UserPromptSubmit", "beforeSubmitPrompt", "UserPromptSubmit"),
        ("Stop", "stop", "Stop"),
    ),
)
def test_native_cursor_owner_covers_imported_claude_event(
    tmp_path,
    runner_event,
    native_event,
    native_runner_event,
) -> None:
    _write_cursor_owner(tmp_path, native_event, native_runner_event)
    environment = {
        "YOKE_HOOK_CONFIG_OWNER": "claude",
        "CURSOR_PROJECT_DIR": str(tmp_path),
    }
    payload = (
        '{"session_id":"cursor-mapped",'
        '"conversation_id":"cursor-mapped"}'
    )

    assert should_skip_config_duplicate(
        runner_event, environment, payload,
    )


@pytest.mark.parametrize("runner_event", ("Stop", "SessionEnd"))
def test_user_backstop_owns_lifecycle_when_project_config_is_missing(
    tmp_path, runner_event,
) -> None:
    machine_home = tmp_path / "machine"
    native_event = "stop" if runner_event == "Stop" else "sessionEnd"
    _write_cursor_owner(
        machine_home,
        native_event,
        runner_event,
        owner="cursor-user-lifecycle",
    )
    payload = (
        '{"session_id":"cursor-degraded",'
        '"conversation_id":"cursor-degraded"}'
    )
    base_environment = {
        "CURSOR_PROJECT_DIR": str(tmp_path / "missing-project"),
        "HOME": str(machine_home),
    }

    assert should_skip_config_duplicate(
        runner_event,
        {**base_environment, "YOKE_HOOK_CONFIG_OWNER": "claude"},
        payload,
    )
    assert not should_skip_config_duplicate(
        runner_event,
        {
            **base_environment,
            "YOKE_HOOK_CONFIG_OWNER": "cursor-user-lifecycle",
        },
        payload,
    )


def test_legacy_user_backstop_stays_owner_until_refresh(tmp_path) -> None:
    machine_home = tmp_path / "machine"
    _write_cursor_owner(
        machine_home,
        "stop",
        "Stop",
        lifecycle_marker=CURSOR_LEGACY_LIFECYCLE_COMMAND_MARKER,
        owner="cursor-user-lifecycle",
    )
    environment = {
        "CURSOR_PROJECT_DIR": str(tmp_path / "missing-project"),
        "HOME": str(machine_home),
        "YOKE_HOOK_CONFIG_OWNER": "claude",
    }
    payload = (
        '{"session_id":"cursor-legacy-user",'
        '"conversation_id":"cursor-legacy-user"}'
    )

    assert should_skip_config_duplicate("Stop", environment, payload)


def test_claude_owned_hook_still_runs_outside_cursor(monkeypatch) -> None:
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('{"session_id":"claude-1"}'),
    )
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    for key in (
        "CURSOR_PROJECT_DIR",
        "CURSOR_TRANSCRIPT_PATH",
        "CURSOR_INVOKED_AS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("transport reached")),
    )

    with pytest.raises(RuntimeError, match="transport reached"):
        cli_main(["hook", "evaluate", "SessionStart"])


def test_ambient_cursor_env_does_not_disable_real_claude_hook(monkeypatch) -> None:
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('{"session_id":"claude-ambient"}'),
    )
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", "/ambient-only")
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("transport reached")),
    )

    with pytest.raises(RuntimeError, match="transport reached"):
        cli_main(["hook", "evaluate", "SessionStart"])


def test_mismatched_cursor_payload_ids_do_not_disable_claude_hook(
    monkeypatch, tmp_path,
) -> None:
    _write_cursor_owner(tmp_path, "sessionStart", "SessionStart")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            '{"session_id":"claude-1","conversation_id":"cursor-1"}'
        ),
    )
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("transport reached")),
    )

    with pytest.raises(RuntimeError, match="transport reached"):
        cli_main(["hook", "evaluate", "SessionStart"])


def test_user_lifecycle_backstop_skips_live_project_owner(
    monkeypatch, tmp_path, capsys,
) -> None:
    _write_cursor_owner(tmp_path, "stop", "Stop")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('{"session_id":"c-1","conversation_id":"c-1"}'),
    )
    monkeypatch.setenv(
        "YOKE_HOOK_CONFIG_OWNER", "cursor-user-lifecycle"
    )
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(
            AssertionError("live project owner must suppress the backstop")
        ),
    )

    assert cli_main(["hook", "evaluate", "Stop"]) == 0
    assert capsys.readouterr().out == "{}"


def test_user_backstop_ignores_unrelated_owner_marker(
    monkeypatch, tmp_path,
) -> None:
    _write_cursor_owner(tmp_path, "stop", "NotStop")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('{"conversation_id":"c-unrelated"}'),
    )
    monkeypatch.setenv(
        "YOKE_HOOK_CONFIG_OWNER", "cursor-user-lifecycle"
    )
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("transport reached")),
    )

    with pytest.raises(RuntimeError, match="transport reached"):
        cli_main(["hook", "evaluate", "Stop"])


def test_user_lifecycle_backstop_runs_without_project_owner(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('{"session_id":"c-2","conversation_id":"c-2"}'),
    )
    monkeypatch.setenv(
        "YOKE_HOOK_CONFIG_OWNER", "cursor-user-lifecycle"
    )
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path / "deleted"))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("transport reached")),
    )

    with pytest.raises(RuntimeError, match="transport reached"):
        cli_main(["hook", "evaluate", "Stop"])
