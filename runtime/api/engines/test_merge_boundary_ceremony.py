"""A standalone item branch cannot be merged from the command line alone.

The merge engine lands a branch; it does not record the item's evidence, sync
GitHub, or drive the terminal transition. Reached directly for a standalone
item branch it therefore prints success for a boundary it did not complete,
which is the shape this guard refuses.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import standalone_item_merge_engine as engine_mod
from yoke_core.engines import merge_worktree as mw
from yoke_core.engines.merge_boundary_ceremony import (
    MERGE_CEREMONY_NONCE_ENV,
    refuse_bare_standalone_merge,
)

BRANCH = "YOK-CEREMONY"


def _no_merge(*_a, **_kw):
    raise AssertionError("a refused boundary must not run the merge engine")


def test_bare_standalone_merge_is_refused_with_the_recovery_recipe(
    monkeypatch, capsys,
):
    monkeypatch.delenv(MERGE_CEREMONY_NONCE_ENV, raising=False)
    monkeypatch.setattr(mw, "run", _no_merge)

    exit_code = mw.main(["--standalone", BRANCH, "main"])

    assert exit_code == 1
    refusal = capsys.readouterr().err
    assert f"yoke merge item {BRANCH}" in refusal
    assert f"/yoke usher {BRANCH}" in refusal
    assert "did not complete" in refusal


def test_epic_lane_merge_is_untouched_by_the_guard(monkeypatch):
    """Only standalone item branches carry item bookkeeping of their own."""
    monkeypatch.delenv(MERGE_CEREMONY_NONCE_ENV, raising=False)
    seen: list = []
    monkeypatch.setattr(mw, "run", lambda args: seen.append(args) or 0)

    assert mw.main([BRANCH, "main", "epic-4"]) == 0
    assert seen and seen[0].epic_ref == "epic-4"


def test_the_sanctioned_in_process_boundary_still_merges(monkeypatch):
    """The boundary that owns the bookkeeping drives the engine directly."""
    monkeypatch.delenv(MERGE_CEREMONY_NONCE_ENV, raising=False)
    seen: list = []
    monkeypatch.setattr(mw, "run", lambda args: seen.append(args) or 0)

    exit_code, _output = engine_mod.run(
        item_id=7, repo_root="/repo", branch=BRANCH,
        source_sha="a" * 40, target="main", local_merge=False,
    )

    assert exit_code == 0
    assert seen and seen[0].standalone is True


def test_a_spent_nonce_admits_one_deliberate_engine_run(
    monkeypatch, tmp_path: Path,
):
    """An operator who means it spends a nonce; it does not survive the run."""
    nonce = tmp_path / "merge-nonce"
    nonce.write_text("ceremony\n", encoding="utf-8")
    monkeypatch.setenv(MERGE_CEREMONY_NONCE_ENV, str(nonce))
    seen: list = []
    monkeypatch.setattr(mw, "run", lambda args: seen.append(args) or 0)

    assert mw.main(["--standalone", BRANCH, "main"]) == 0
    assert seen and seen[0].standalone is True
    assert not nonce.exists()
    assert refuse_bare_standalone_merge(BRANCH) != ""


def test_an_empty_nonce_file_does_not_admit_a_merge(
    monkeypatch, tmp_path: Path,
):
    nonce = tmp_path / "merge-nonce"
    nonce.write_text("   \n", encoding="utf-8")
    monkeypatch.setenv(MERGE_CEREMONY_NONCE_ENV, str(nonce))

    assert "missing merge-boundary ceremony nonce" in refuse_bare_standalone_merge(
        BRANCH
    )
