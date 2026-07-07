"""Tests for the ``yoke scratch dispatch-inputs`` CLI adapter."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters.misc import scratch_dispatch_inputs
from yoke_core.domain import project_scratch_dir as scratch


@pytest.fixture
def scoped_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path))
    return tmp_path


def _stub_resolve(raw, project=None, session_id=None) -> int:
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    if "-" in text:
        return int(text.rsplit("-", 1)[1])
    raise ValueError(f"invalid item ref: {raw!r}")


@pytest.fixture(autouse=True)
def _stub_dispatch_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    # The adapter resolves the numeric id through the dispatcher (relay
    # contract); these tests cover the path computation, not resolution.
    monkeypatch.setattr(
        "yoke_cli.commands.adapters.misc."
        "resolve_item_id_via_dispatch",
        _stub_resolve,
    )


def _run(args, capsys):
    rc = scratch_dispatch_inputs(args)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_adapter_prints_one_absolute_path_line(
    scoped_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    rc, out, err = _run(["1846", "session-abc", "1"], capsys)

    assert rc == 0
    assert err == ""
    assert out.endswith("\n")
    lines = out.splitlines()
    assert len(lines) == 1
    path = Path(lines[0])
    assert path.is_absolute()
    assert path.name == "attempt-1"
    assert path.parent.name == "session-abc"
    assert path.parent.parent.name == "YOK-1846"
    # Helper creates the directory by default — the shepherd skill needs
    # mkdir-by-default so the printf >file works without a separate mkdir.
    assert path.is_dir()


def test_adapter_accepts_bare_integer_item_id(
    scoped_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    rc, out, _err = _run(["42", "sid", "2"], capsys)

    assert rc == 0
    path = Path(out.strip())
    assert path.parent.parent.name == "YOK-42"


def test_adapter_rejects_missing_args(
    scoped_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    rc, _out, err = _run([], capsys)

    assert rc == 2
    assert err  # argparse usage on stderr


def test_adapter_rejects_non_integer_attempt(
    scoped_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    rc, _out, err = _run(["1", "sid", "not-int"], capsys)

    assert rc != 0
    assert "attempt" in err


def test_adapter_rejects_attempt_zero(
    scoped_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    rc, _out, err = _run(["1", "sid", "0"], capsys)

    assert rc != 0
    assert "attempt" in err


def test_adapter_rejects_empty_session_id(
    scoped_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    rc, _out, err = _run(["1", "   ", "1"], capsys)

    assert rc != 0
    assert "session_id" in err


def test_adapter_no_banner_no_trailing_whitespace(
    scoped_scratch: Path, capsys: pytest.CaptureFixture
) -> None:
    """Shepherd skill captures via $(...); banners or extra blank lines
    would silently break the capture."""

    rc, out, _err = _run(["1846", "SESSION_FAKE", "1"], capsys)

    assert rc == 0
    assert out.count("\n") == 1
    assert not out.startswith(" ")
    # Exactly one path-shaped token.
    assert out.strip() == out.rstrip("\n")
