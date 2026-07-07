"""Tests for the canonical runtime-settings reader."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from yoke_core.domain import runtime_settings


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "config"
    cfg.write_text(body, encoding="utf-8")
    return cfg


# ---------------------------------------------------------------------------
# get_str
# ---------------------------------------------------------------------------


def test_get_str_returns_value_when_present(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "monitor_hint_color=C5DEF5\n")
    assert (
        runtime_settings.get_str("monitor_hint_color", "fallback", config_path=cfg)
        == "C5DEF5"
    )


def test_get_str_returns_default_when_key_missing(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "other=value\n")
    assert (
        runtime_settings.get_str("monitor_hint_color", "fallback", config_path=cfg)
        == "fallback"
    )


def test_get_str_returns_default_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "config"
    assert (
        runtime_settings.get_str("any_key", "fallback", config_path=missing)
        == "fallback"
    )


def test_get_str_strips_inline_comments(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "monitor_hint_color=C5DEF5  # azure\n")
    assert (
        runtime_settings.get_str("monitor_hint_color", "", config_path=cfg)
        == "C5DEF5"
    )


def test_get_str_strips_surrounding_quotes(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path, 'monitor_relay_hint_text="hello world"\n'
    )
    assert (
        runtime_settings.get_str(
            "monitor_relay_hint_text", "", config_path=cfg
        )
        == "hello world"
    )


def test_get_str_skips_blank_lines_and_comment_lines(tmp_path: Path) -> None:
    body = (
        "# header\n"
        "\n"
        "  # indented comment\n"
        "monitor_hint_color=C5DEF5\n"
    )
    cfg = _write_config(tmp_path, body)
    assert (
        runtime_settings.get_str("monitor_hint_color", "x", config_path=cfg)
        == "C5DEF5"
    )


# ---------------------------------------------------------------------------
# get_int
# ---------------------------------------------------------------------------


def test_get_int_parses_integer(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "wip_cap=5\n")
    assert runtime_settings.get_int("wip_cap", 0, config_path=cfg) == 5


def test_get_int_returns_default_when_missing(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "other=value\n")
    assert runtime_settings.get_int("wip_cap", 7, config_path=cfg) == 7


def test_get_int_returns_default_when_malformed(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "wip_cap=not-an-integer\n")
    assert runtime_settings.get_int("wip_cap", 7, config_path=cfg) == 7


def test_get_int_accepts_negative_value(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "offset=-3\n")
    assert runtime_settings.get_int("offset", 0, config_path=cfg) == -3


# ---------------------------------------------------------------------------
# get_seconds
# ---------------------------------------------------------------------------


def test_get_seconds_parses_positive_integer(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "git_fetch_timeout_seconds=120\n")
    assert (
        runtime_settings.get_seconds(
            "git_fetch_timeout_seconds", 60, config_path=cfg
        )
        == 120
    )


def test_get_seconds_returns_default_for_non_positive(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "git_fetch_timeout_seconds=0\n")
    assert (
        runtime_settings.get_seconds(
            "git_fetch_timeout_seconds", 60, config_path=cfg
        )
        == 60
    )


def test_get_seconds_returns_default_for_negative(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "git_fetch_timeout_seconds=-30\n")
    assert (
        runtime_settings.get_seconds(
            "git_fetch_timeout_seconds", 60, config_path=cfg
        )
        == 60
    )


def test_get_seconds_returns_default_for_malformed(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "git_fetch_timeout_seconds=oops\n")
    assert (
        runtime_settings.get_seconds(
            "git_fetch_timeout_seconds", 60, config_path=cfg
        )
        == 60
    )


# ---------------------------------------------------------------------------
# read_all
# ---------------------------------------------------------------------------


def test_read_all_returns_dict(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, "a=1\nb=hello\n# comment\nc=true\n")
    parsed = runtime_settings.read_all(config_path=cfg)
    assert parsed == {"a": "1", "b": "hello", "c": "true"}


def test_read_all_strips_whitespace_and_inline_comments(tmp_path: Path) -> None:
    body = "monitor_hint_color=FBCA04                # yellow\n"
    cfg = _write_config(tmp_path, body)
    parsed = runtime_settings.read_all(config_path=cfg)
    assert parsed == {"monitor_hint_color": "FBCA04"}


def test_read_all_returns_empty_for_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "no-config"
    assert runtime_settings.read_all(config_path=missing) == {}


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_get_prints_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"schema_version": 1, "settings": {"monitor_hint_color": "FBCA04"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(cfg))
    rc = runtime_settings.main(["get", "monitor_hint_color", "fallback"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "FBCA04"


def test_cli_get_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"schema_version": 1, "settings": {}}), encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(cfg))
    rc = runtime_settings.main(["get", "monitor_hint_color", "fallback"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == "fallback"


def test_cli_usage_on_missing_subcommand(
    capsys: pytest.CaptureFixture,
) -> None:
    rc = runtime_settings.main([])
    err = capsys.readouterr().err
    assert rc == 0
    assert "runtime_settings get" in err


# ---------------------------------------------------------------------------
# canonical resolver fallthrough
# ---------------------------------------------------------------------------


def test_default_reader_resolves_machine_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"schema_version": 1, "settings": {"monitor_hint_color": "mocked"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(cfg))
    monkeypatch.delenv("YOKE_ROOT", raising=False)
    assert runtime_settings.get_str("monitor_hint_color", "x") == "mocked"
