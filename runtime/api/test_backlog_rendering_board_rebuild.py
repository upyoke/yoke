"""Board rebuild skips gracefully when there is no checkout.

Regression: a server-side https `items.create` (an `/yoke idea` filed
against a prod control plane) inserted the item + synced GitHub, then raised
"Cannot determine repo root" rebuilding the client-local BOARD.md — failing
the whole create. The board is a client-local view; skip it server-side.

A later regression: hosted lifecycle transitions still *printed* the
``[no-checkout]`` advisory into the response log even though the server has
no checkout by design. Hosted/self-host stay silent; a local rootless client
still gets the advisory.
"""

from __future__ import annotations

import io

import pytest

from yoke_core.domain import backlog_rendering as br
from yoke_core.domain import rebuild_board as rb


def test_rebuild_board_skips_without_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise():
        raise RuntimeError("Cannot determine repo root")

    monkeypatch.setattr(br, "_yoke_root", _raise)
    monkeypatch.setattr(rb, "no_checkout_board_skip_is_expected", lambda: False)
    out = io.StringIO()
    br._rebuild_board(out)  # must NOT raise
    assert "Skipping board rebuild" in out.getvalue()
    assert "no-checkout" in out.getvalue()


def test_rebuild_board_silent_when_no_checkout_expected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise():
        raise RuntimeError("Cannot determine repo root")

    monkeypatch.setattr(br, "_yoke_root", _raise)
    monkeypatch.setattr(rb, "no_checkout_board_skip_is_expected", lambda: True)
    out = io.StringIO()
    br._rebuild_board(out)  # must NOT raise
    assert out.getvalue() == ""
