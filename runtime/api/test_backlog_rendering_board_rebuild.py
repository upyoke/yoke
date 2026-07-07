"""Board rebuild skips gracefully when there is no checkout.

Regression: a server-side https `items.create` (an `/yoke idea` filed
against a prod control plane) inserted the item + synced GitHub, then raised
"Cannot determine repo root" rebuilding the client-local BOARD.md — failing
the whole create. The board is a client-local view; skip it server-side.
"""

from __future__ import annotations

import io

import pytest

from yoke_core.domain import backlog_rendering as br


def test_rebuild_board_skips_without_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise():
        raise RuntimeError("Cannot determine repo root")

    monkeypatch.setattr(br, "_yoke_root", _raise)
    out = io.StringIO()
    br._rebuild_board(out)  # must NOT raise
    assert "Skipping board rebuild" in out.getvalue()
    assert "no-checkout" in out.getvalue()
