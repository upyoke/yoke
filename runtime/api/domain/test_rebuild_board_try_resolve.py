"""``try_resolve_main_repo_root`` returns None (no raise) when there's no
checkout — the shared no-checkout-safe resolver behind the server-side guards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import rebuild_board as rb


def test_returns_none_on_filenotfound(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise FileNotFoundError("Could not find project repo root.")

    monkeypatch.setattr(rb, "resolve_main_repo_root", _raise)
    assert rb.try_resolve_main_repo_root() is None


def test_returns_none_on_runtimeerror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise RuntimeError("Cannot determine repo root")

    monkeypatch.setattr(rb, "resolve_main_repo_root", _raise)
    assert rb.try_resolve_main_repo_root() is None


def test_passes_through_a_real_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(rb, "resolve_main_repo_root", lambda *a, **k: tmp_path)
    assert rb.try_resolve_main_repo_root() == tmp_path
