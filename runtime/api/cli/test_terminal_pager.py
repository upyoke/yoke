"""Tests for the git-style terminal pager helper."""

from __future__ import annotations

from typing import List

from yoke_cli import terminal_pager
from yoke_cli.terminal_pager import (
    page_or_write,
    resolve_pager,
    should_paginate,
)


class _FakeStream:
    """Minimal text stream with a controllable ``isatty``."""

    def __init__(self, *, tty: bool) -> None:
        self._tty = tty
        self.chunks: List[str] = []
        self.flushed = False

    def isatty(self) -> bool:
        return self._tty

    def write(self, s: str) -> int:
        self.chunks.append(s)
        return len(s)

    def flush(self) -> None:
        self.flushed = True

    @property
    def text(self) -> str:
        return "".join(self.chunks)


def _clear_pager_env(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.delenv("PAGER", raising=False)


# --- resolve_pager precedence -------------------------------------------


def test_resolve_pager_defaults_to_less(monkeypatch) -> None:
    _clear_pager_env(monkeypatch)
    assert resolve_pager() == "less"


def test_resolve_pager_yoke_pager_wins(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_PAGER", "most")
    monkeypatch.setenv("PAGER", "less")
    assert resolve_pager() == "most"


def test_resolve_pager_falls_back_to_pager(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "less -R")
    assert resolve_pager() == "less -R"


def test_resolve_pager_cat_disables(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "cat")
    assert resolve_pager() is None


def test_resolve_pager_empty_disables(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_PAGER", "")
    assert resolve_pager() is None


# --- should_paginate gate -----------------------------------------------


def test_should_paginate_false_when_not_tty(monkeypatch) -> None:
    _clear_pager_env(monkeypatch)
    assert should_paginate(_FakeStream(tty=False)) is False


def test_should_paginate_false_when_disabled(monkeypatch) -> None:
    _clear_pager_env(monkeypatch)
    assert should_paginate(_FakeStream(tty=True), enabled=False) is False


def test_should_paginate_false_when_pager_disabled(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "cat")
    assert should_paginate(_FakeStream(tty=True)) is False


def test_should_paginate_true_when_tty_and_pager(monkeypatch) -> None:
    _clear_pager_env(monkeypatch)
    assert should_paginate(_FakeStream(tty=True)) is True


# --- page_or_write: direct-write paths ----------------------------------


def test_page_or_write_direct_when_not_tty(monkeypatch) -> None:
    _clear_pager_env(monkeypatch)
    stream = _FakeStream(tty=False)
    page_or_write("hello\n", stream=stream)
    assert stream.text == "hello\n"
    assert stream.flushed is True


def test_page_or_write_direct_when_disabled(monkeypatch) -> None:
    _clear_pager_env(monkeypatch)
    stream = _FakeStream(tty=True)
    page_or_write("hello\n", stream=stream, enabled=False)
    assert stream.text == "hello\n"


# --- page_or_write: pager-spawning paths --------------------------------


def test_page_or_write_spawns_pager_when_tty(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "less")
    monkeypatch.delenv("LESS", raising=False)
    captured: dict = {}

    class _FakeProc:
        def communicate(self, content: str) -> None:
            captured["content"] = content

    def _fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        captured["text"] = kwargs.get("text")
        return _FakeProc()

    monkeypatch.setattr(terminal_pager.shutil, "which", lambda _name: "/usr/bin/less")
    monkeypatch.setattr(terminal_pager.subprocess, "Popen", _fake_popen)

    stream = _FakeStream(tty=True)
    page_or_write("BOARD\n", stream=stream)

    assert captured["argv"] == ["less"]
    assert captured["content"] == "BOARD\n"
    assert captured["text"] is True
    assert captured["env"]["LESS"] == "FRX"
    # Content went to the pager, not straight to the stream.
    assert stream.chunks == []


def test_page_or_write_respects_preset_less_env(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "less")
    monkeypatch.setenv("LESS", "SR")  # operator's own LESS must win
    captured: dict = {}

    class _FakeProc:
        def communicate(self, content: str) -> None:
            captured["content"] = content

    def _fake_popen(argv, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeProc()

    monkeypatch.setattr(terminal_pager.shutil, "which", lambda _name: "/usr/bin/less")
    monkeypatch.setattr(terminal_pager.subprocess, "Popen", _fake_popen)

    page_or_write("BOARD\n", stream=_FakeStream(tty=True))
    assert captured["env"]["LESS"] == "SR"


def test_page_or_write_falls_back_when_pager_missing(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "less")
    monkeypatch.setattr(terminal_pager.shutil, "which", lambda _name: None)

    def _boom(*_a, **_k):
        raise AssertionError("Popen must not run when the pager binary is missing")

    monkeypatch.setattr(terminal_pager.subprocess, "Popen", _boom)

    stream = _FakeStream(tty=True)
    page_or_write("BOARD\n", stream=stream)
    assert stream.text == "BOARD\n"


def test_page_or_write_falls_back_on_popen_oserror(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "less")
    monkeypatch.setattr(terminal_pager.shutil, "which", lambda _name: "/usr/bin/less")

    def _raise(*_a, **_k):
        raise OSError("exec format error")

    monkeypatch.setattr(terminal_pager.subprocess, "Popen", _raise)

    stream = _FakeStream(tty=True)
    page_or_write("BOARD\n", stream=stream)
    assert stream.text == "BOARD\n"


def test_page_or_write_broken_pipe_does_not_double_write(monkeypatch) -> None:
    monkeypatch.delenv("YOKE_PAGER", raising=False)
    monkeypatch.setenv("PAGER", "less")

    class _FakeProc:
        def communicate(self, _content: str) -> None:
            raise BrokenPipeError()

    monkeypatch.setattr(terminal_pager.shutil, "which", lambda _name: "/usr/bin/less")
    monkeypatch.setattr(terminal_pager.subprocess, "Popen", lambda *_a, **_k: _FakeProc())

    stream = _FakeStream(tty=True)
    page_or_write("BOARD\n", stream=stream)
    # The pager ran (user quit early); no direct-write fallback.
    assert stream.chunks == []


# --- _pager_argv parsing -------------------------------------------------


def test_pager_argv_splits_arguments(monkeypatch) -> None:
    monkeypatch.setattr(terminal_pager.shutil, "which", lambda _name: "/usr/bin/less")
    assert terminal_pager._pager_argv("less -R") == ["less", "-R"]


def test_pager_argv_none_when_binary_missing(monkeypatch) -> None:
    monkeypatch.setattr(terminal_pager.shutil, "which", lambda _name: None)
    assert terminal_pager._pager_argv("less") is None


def test_pager_argv_none_when_empty() -> None:
    assert terminal_pager._pager_argv("") is None
