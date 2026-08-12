"""``emit_no_checkout_board_skip`` is silent on hosted/self-host and advises
locally when a checkout is expected but missing.
"""

from __future__ import annotations

import io

import pytest

from yoke_core.domain import rebuild_board as rb


def test_emit_silent_when_expected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rb, "no_checkout_board_skip_is_expected", lambda: True)
    out = io.StringIO()
    rb.emit_no_checkout_board_skip(RuntimeError("Cannot determine repo root"), out)
    assert out.getvalue() == ""


def test_emit_advisory_when_local_rootless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rb, "no_checkout_board_skip_is_expected", lambda: False)
    out = io.StringIO()
    rb.emit_no_checkout_board_skip(RuntimeError("Cannot determine repo root"), out)
    text = out.getvalue()
    assert "no-checkout" in text
    assert "Skipping board rebuild" in text


def test_expected_true_for_self_host_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_SERVER_MODE", "self-host")
    assert rb.no_checkout_board_skip_is_expected() is True


def test_expected_false_when_source_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    monkeypatch.delenv("YOKE_SERVER_MODE", raising=False)
    monkeypatch.setattr(rb, "mapped_checkouts", lambda _payload: [])
    monkeypatch.setattr(
        rb, "source_checkout_root", lambda _path: Path("/fake/yoke")
    )
    assert rb.no_checkout_board_skip_is_expected() is False


def test_expected_true_without_map_or_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YOKE_SERVER_MODE", raising=False)
    monkeypatch.setattr(rb, "mapped_checkouts", lambda _payload: [])
    monkeypatch.setattr(rb, "source_checkout_root", lambda _path: None)
    assert rb.no_checkout_board_skip_is_expected() is True
