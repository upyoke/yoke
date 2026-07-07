"""The epic-task lineage's board rebuild skips with an advisory when there is
no checkout, and is best-effort: a rebuild failure never fails the transition.
"""

from __future__ import annotations

import io

import pytest

from yoke_core.domain import update_status_helpers as ush


def test_rebuild_board_skips_with_advisory(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise():
        raise RuntimeError("Cannot determine repo root")

    monkeypatch.setattr(ush, "_repo_root", _raise)
    out = io.StringIO()
    ush._rebuild_board(out)  # must NOT raise
    assert "Skipping board rebuild" in out.getvalue()
    assert "no-checkout" in out.getvalue()


def test_rebuild_failure_is_nonfatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    # The board is a generated view: a rebuild failure must NOT fail the
    # status transition — it is swallowed (best-effort), never propagated.
    import yoke_core.domain.rebuild_board as rb

    monkeypatch.setattr(ush, "_repo_root", lambda: tmp_path)

    def _boom(*a, **k):
        raise ValueError("rebuild kaboom")

    monkeypatch.setattr(rb, "rebuild", _boom)
    ush._rebuild_board(io.StringIO())  # must NOT raise
