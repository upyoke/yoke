"""Focused tests for ``yoke board rebuild`` print modes."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.board import rebuild as board_rebuild
from yoke_cli.board import outcome as rb_outcome
from yoke_cli.commands.board_terminal_output import (
    format_data_source,
    plain_board_reason,
)
from yoke_cli.config import machine_config


def _configured_project(checkout: Path, project_id: int) -> machine_config.ConfiguredProject:
    return machine_config.ConfiguredProject(
        checkout=checkout,
        project_id=project_id,
        entry={"project_id": project_id},
    )


def test_resolve_board_project_from_registered_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "externalwebapp"
    nested = checkout / "src"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [_configured_project(checkout, 37)],
    )

    assert board_rebuild.resolve_main_repo_root() == checkout.resolve()


def test_resolve_board_project_rejects_home_machine_yoke_with_multiple_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".yoke").mkdir()
    externalwebapp = tmp_path / "externalwebapp"
    yoke = tmp_path / "yoke"
    externalwebapp.mkdir()
    yoke.mkdir()
    monkeypatch.chdir(home)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [
            _configured_project(externalwebapp, 37),
            _configured_project(yoke, 1),
        ],
    )

    with pytest.raises(board_rebuild.BoardProjectResolutionError, match="could not choose"):
        board_rebuild.resolve_main_repo_root()


def test_resolve_board_project_falls_back_to_cwd_when_env_is_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "externalwebapp"
    nested = checkout / "src"
    home.mkdir()
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(home))
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [_configured_project(checkout, 37)],
    )

    assert board_rebuild.resolve_main_repo_root() == checkout.resolve()


def test_resolve_board_project_uses_single_registered_project_from_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "externalwebapp"
    home.mkdir()
    checkout.mkdir()
    monkeypatch.chdir(home)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [_configured_project(checkout, 37)],
    )

    assert board_rebuild.resolve_main_repo_root() == checkout.resolve()


def test_resolve_board_project_rejects_unregistered_explicit_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "externalwebapp"
    other = tmp_path / "other"
    checkout.mkdir()
    other.mkdir()
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [_configured_project(checkout, 37)],
    )

    with pytest.raises(board_rebuild.BoardProjectResolutionError, match="not inside"):
        board_rebuild.resolve_main_repo_root(str(other))


def test_board_rebuild_fails_cleanly_when_project_is_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "home"
    externalwebapp = tmp_path / "externalwebapp"
    yoke = tmp_path / "yoke"
    outside.mkdir()
    externalwebapp.mkdir()
    yoke.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(
        machine_config,
        "configured_projects",
        lambda **_: [
            _configured_project(externalwebapp, 37),
            _configured_project(yoke, 1),
        ],
    )

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc = cli_main(["board", "rebuild", "--print"])

    assert rc == 2
    assert stdout.getvalue() == ""
    assert "could not choose a board project" in stderr.getvalue()


def test_print_rebuilds_then_prints_board_to_stdout(tmp_path: Path) -> None:
    board_path = tmp_path / ".yoke" / "BOARD.md"

    def _fake_rebuild(**_kwargs):
        board_path.parent.mkdir(parents=True, exist_ok=True)
        board_path.write_text("BOARD CONTENT\n", encoding="utf-8")
        return rb_outcome.rebuilt(board_path)

    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict("os.environ", {
        "YOKE_SESSION_ID": "test-session",
        "TERM": "xterm-256color",
    }):
        with patch(
            "yoke_cli.board.rebuild.rebuild",
            side_effect=_fake_rebuild,
        ) as rebuild:
            with patch(
                "yoke_cli.board.rebuild.resolve_main_repo_root",
                return_value=tmp_path,
            ):
                with patch("yoke_core.cli.board_rebuild_timing_events.emit_event"):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        rc = cli_main(["board", "rebuild", "--print"])

    assert rc == 0
    assert stdout.getvalue() == (
        f"Yoke board source: scope=all checkout={tmp_path} "
        f"board={board_path}\n\n"
        "BOARD CONTENT\n"
    )
    assert "Board rebuilt:" in stderr.getvalue()
    rebuild.assert_called_once()


def test_print_banner_includes_active_data_source(tmp_path: Path) -> None:
    board_path = tmp_path / ".yoke" / "BOARD.md"

    def _fake_rebuild(**_kwargs):
        board_path.parent.mkdir(parents=True, exist_ok=True)
        board_path.write_text("BOARD CONTENT\n", encoding="utf-8")
        return rb_outcome.rebuilt(board_path)

    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict("os.environ", {
        "YOKE_SESSION_ID": "test-session",
        "TERM": "xterm-256color",
    }):
        with patch(
            "yoke_cli.board.rebuild.rebuild",
            side_effect=_fake_rebuild,
        ), patch(
            "yoke_cli.board.rebuild.resolve_main_repo_root",
            return_value=tmp_path,
        ), patch(
            "yoke_core.cli.board_rebuild_timing_events.emit_event"
        ), patch(
            "yoke_cli.commands.adapters.board.machine_config.active_connection",
            return_value={
                "transport": "https",
                "api_url": "https://api.stage.upyoke.com/",
            },
        ), patch(
            "yoke_cli.commands.adapters.board.machine_config.active_env",
            return_value="stage",
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = cli_main(["board", "rebuild", "--print"])

    assert rc == 0
    first_line = stdout.getvalue().splitlines()[0]
    assert "env=stage" in first_line
    assert "scope=all" in first_line
    assert f"checkout={tmp_path}" in first_line
    assert f"board={board_path}" in first_line
    assert "data=https://api.stage.upyoke.com" in first_line


def test_print_only_renders_without_writing_board(tmp_path: Path) -> None:
    board_path = tmp_path / ".yoke" / "BOARD.md"

    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict("os.environ", {
        "YOKE_SESSION_ID": "test-session",
        "TERM": "xterm-256color",
    }):
        with patch("yoke_cli.board.rebuild.rebuild") as rebuild:
            with patch(
                "yoke_cli.board.rebuild.resolve_main_repo_root",
                return_value=tmp_path,
            ):
                with patch(
                    "yoke_cli.board.rebuild.render_text",
                    return_value=(tmp_path, board_path, "FRESH BOARD\n"),
                ) as render_text:
                    with patch(
                        "yoke_core.cli.board_rebuild_timing_events.emit_event"
                    ) as emit_event:
                        with redirect_stdout(stdout), redirect_stderr(stderr):
                            rc = cli_main(["board", "rebuild", "--print-only"])

    assert rc == 0
    assert stdout.getvalue() == (
        f"Yoke board source: scope=all checkout={tmp_path} "
        f"board={board_path}\n\n"
        "FRESH BOARD\n"
    )
    assert "Board rendered:" in stderr.getvalue()
    rebuild.assert_not_called()
    render_text.assert_called_once()
    assert not board_path.exists()
    assert not Path(f"{board_path}.ts").exists()
    completed = emit_event.call_args_list[-1].kwargs
    assert completed["context"]["status"] == "printed"
    assert completed["context"]["changed"] is False
    assert completed["context"]["print_mode"] == "print_only"



def test_json_mode_rejects_print_modes() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc = cli_main(["board", "rebuild", "--json", "--print"])

    assert rc == 2
    assert stdout.getvalue() == ""
    assert "--json cannot be combined" in stderr.getvalue()


def _run_print_capturing_pager(
    tmp_path: Path,
    extra_args: list[str],
    *,
    env_extra: dict[str, str] | None = None,
) -> dict:
    """Run ``board rebuild --print`` with ``page_or_write`` stubbed out.

    Returns the kwargs the print path handed the pager so tests can assert
    how the ``--no-pager`` flag threads through.
    """
    board_path = tmp_path / ".yoke" / "BOARD.md"

    def _fake_rebuild(**_kwargs):
        board_path.parent.mkdir(parents=True, exist_ok=True)
        board_path.write_text("🏆 BOARD █ CONTENT └ done\n", encoding="utf-8")
        return rb_outcome.rebuilt(board_path)

    captured: dict = {}

    def _fake_page_or_write(content, *, stream=None, enabled=True):
        captured["content"] = content
        captured["enabled"] = enabled

    env = {"YOKE_SESSION_ID": "test-session", "TERM": "xterm-256color"}
    if env_extra:
        env.update(env_extra)
    with patch.dict("os.environ", env):
        with patch(
            "yoke_cli.board.rebuild.rebuild", side_effect=_fake_rebuild
        ):
            with patch(
                "yoke_cli.board.rebuild.resolve_main_repo_root",
                return_value=tmp_path,
            ):
                with patch("yoke_core.cli.board_rebuild_timing_events.emit_event"):
                    with patch(
                        "yoke_cli.commands.board_rebuild_output.page_or_write",
                        _fake_page_or_write,
                    ):
                        with redirect_stdout(io.StringIO()), redirect_stderr(
                            io.StringIO()
                        ):
                            rc = cli_main(["board", "rebuild", "--print", *extra_args])

    captured["rc"] = rc
    return captured


def test_print_enables_pager_by_default(tmp_path: Path) -> None:
    captured = _run_print_capturing_pager(tmp_path, extra_args=[])
    assert captured["rc"] == 0
    assert "Yoke board source:" in captured["content"]
    assert "🏆 BOARD █ CONTENT └ done" in captured["content"]
    assert captured["enabled"] is True


def test_no_pager_flag_disables_pager(tmp_path: Path) -> None:
    captured = _run_print_capturing_pager(tmp_path, extra_args=["--no-pager"])
    assert captured["rc"] == 0
    assert "Yoke board source:" in captured["content"]
    assert "🏆 BOARD █ CONTENT └ done" in captured["content"]
    assert captured["enabled"] is False


def test_screen_terminal_prints_plain_board(tmp_path: Path) -> None:
    captured = _run_print_capturing_pager(
        tmp_path,
        extra_args=[],
        env_extra={"TERM": "screen-256color"},
    )
    assert captured["rc"] == 0
    assert "Yoke board terminal mode: plain" in captured["content"]
    assert "🏆" not in captured["content"]
    assert "█" not in captured["content"]
    assert "└" not in captured["content"]
    assert "TERM=screen-256color" in captured["content"]
    assert "* BOARD # CONTENT + done" in captured["content"]


def test_plain_board_reason_allows_rich_override() -> None:
    env = {"TERM": "screen-256color", "STY": "1234.tty", "YOKE_BOARD_RICH": "1"}
    assert plain_board_reason(env) == ""


def test_format_data_source_uses_endpoint_without_secret_material() -> None:
    assert (
        format_data_source({
            "transport": "https",
            "api_url": "https://api.stage.upyoke.com/",
            "credential_source": {
                "kind": "token_file",
                "path": "/Users/testy/.yoke/secrets/stage.token",
            },
        })
        == "https://api.stage.upyoke.com"
    )
    assert format_data_source({"transport": "local-postgres"}) == "local-postgres"
