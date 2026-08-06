"""Cursor lifecycle config owners emit one valid response."""

from __future__ import annotations

import builtins
import io
import json
import sys

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.transport.https import TransportError
from yoke_core.domain.agents_render_hooks import render_cursor_hooks_block
from yoke_harness.hooks.cursor_lifecycle_hooks import (
    ensure_user_lifecycle_hooks,
)


@pytest.mark.parametrize("event_name", ("Stop", "SessionEnd"))
@pytest.mark.parametrize("winning_owner", ("project", "user"))
def test_imported_claude_lifecycle_loser_emits_empty_object(
    monkeypatch, tmp_path, capsys, event_name, winning_owner,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    if winning_owner == "project":
        cursor = project / ".cursor"
        cursor.mkdir(parents=True)
        (cursor / "hooks.json").write_text(
            json.dumps(render_cursor_hooks_block()), encoding="utf-8",
        )
    else:
        ensure_user_lifecycle_hooks(
            hooks_path=home / ".cursor" / "hooks.json",
        )
    session_id = f"cursor-{winning_owner}-{event_name}"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({
            "session_id": session_id,
            "conversation_id": session_id,
        })),
    )
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(project))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(
            AssertionError("losing config must not reach transport")
        ),
    )

    assert cli_main(["hook", "evaluate", event_name]) == 0
    assert capsys.readouterr().out == "{}"


def _cursor_hook_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            '{"session_id":"cursor-degraded",'
            '"conversation_id":"cursor-degraded"}'
        ),
    )
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "cursor-project")
    monkeypatch.setenv("YOKE_EXECUTOR", "cursor")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))


def test_missing_harness_lifecycle_degradation_emits_empty_object(
    monkeypatch, tmp_path, capsys,
) -> None:
    _cursor_hook_environment(monkeypatch, tmp_path)
    real_import = builtins.__import__

    def import_without_harness(name, *args, **kwargs):
        if name == "yoke_harness.hooks.relay":
            raise ImportError("isolated missing harness")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_harness)

    assert cli_main(["hook", "evaluate", "Stop"]) == 0
    output = capsys.readouterr()
    assert output.out == "{}"
    assert "yoke-harness unavailable" in output.err


def test_unmarked_legacy_cursor_command_degrades_with_empty_object(
    monkeypatch, capsys,
) -> None:
    monkeypatch.setenv("YOKE_EXECUTOR", "cursor")
    monkeypatch.delenv("YOKE_HOOK_CONFIG_OWNER", raising=False)
    real_import = builtins.__import__

    def import_without_harness(name, *args, **kwargs):
        if name == "yoke_harness.hooks.relay":
            raise ImportError("isolated missing harness")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_harness)

    assert cli_main(["hook", "evaluate", "Stop"]) == 0
    output = capsys.readouterr()
    assert output.out == "{}"
    assert "yoke-harness unavailable" in output.err


def test_half_configured_https_lifecycle_degradation_emits_empty_object(
    monkeypatch, tmp_path, capsys,
) -> None:
    _cursor_hook_environment(monkeypatch, tmp_path)

    def unresolved_connection() -> None:
        raise TransportError("https connection is incomplete")

    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        unresolved_connection,
    )

    assert cli_main(["hook", "evaluate", "SessionEnd"]) == 0
    output = capsys.readouterr()
    assert output.out == "{}"
    assert "degraded to no-op allow" in output.err
