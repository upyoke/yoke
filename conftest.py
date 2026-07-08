"""Shared pytest fixtures for repo-wide Yoke tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_core.tools import build_release


REPO_ROOT = Path(__file__).resolve().parent
PRODUCT_WHEELHOUSE_PACKAGES = build_release.PRODUCT_PACKAGE_NAMES


@pytest.fixture(autouse=True)
def _isolate_commit_cache(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the on-disk commit/activity caches to a per-test tmp dir.

    Both caches resolve their file location through
    ``machine_config.cache_dir()`` (``~/.yoke/cache`` by default). Tests
    that rebuild the board against real temp repos otherwise write their
    throwaway-repo entries into the developer's real cache and, under xdist,
    race each other's writes there — pollution that evicted real-repo entries
    from the production cache. This monkeypatch pins the path for IN-PROCESS
    ``get_commit_data`` calls, and lives at the repo root so it covers the whole
    canonical suite (``runtime/api`` ∪ ``runtime/harness`` ∪ ``tests``).

    It CANNOT reach a spawned interpreter — a monkeypatch does not cross the
    process boundary. Subprocess board rebuilds stay off the real cache by two
    other routes, both relying on ``cache_dir()`` anchoring under
    ``yoke_home()``: the merge-worktree engine subprocess inherits the isolated
    ``YOKE_MACHINE_HOME`` its parent test sets; the core-less rebuild smoke,
    which sets no machine home, pins an explicit ``cache_dir`` in its child's
    machine config (see ``test_board_rebuild_core_less_smoke``).
    """
    from yoke_contracts.board import widgets_commit_cache as _commit_cache
    from yoke_contracts.board import activity_cache as _activity_cache

    monkeypatch.setattr(
        _commit_cache, "_cache_path",
        lambda: tmp_path / "cache" / ".commit-cache.json",
    )
    monkeypatch.setattr(
        _activity_cache, "_cache_path",
        lambda: tmp_path / "cache" / "board-activity-day-counts.json",
    )
    _commit_cache._reset_memo_for_tests()
    yield
    _commit_cache._reset_memo_for_tests()


@pytest.fixture(scope="session")
def product_wheelhouse(tmp_path_factory, pytestconfig: pytest.Config) -> Path:
    """Build the client product wheels once per pytest run."""
    worker_id = _worker_id(pytestconfig)
    if worker_id == "master":
        wheelhouse = tmp_path_factory.mktemp("product_wheelhouse")
        _build_wheelhouse(REPO_ROOT, wheelhouse)
        _write_product_wheelhouse_sentinel(wheelhouse)
        return wheelhouse

    shared_root = tmp_path_factory.getbasetemp().parent
    wheelhouse = shared_root / "product_wheelhouse"
    sentinel = wheelhouse / ".built.json"
    from filelock import FileLock

    with FileLock(str(shared_root / "product_wheelhouse.lock")):
        if not sentinel.exists():
            _build_wheelhouse(REPO_ROOT, wheelhouse)
            _write_product_wheelhouse_sentinel(wheelhouse)
    return wheelhouse


def _worker_id(pytestconfig: pytest.Config) -> str:
    worker_input = getattr(pytestconfig, "workerinput", None)
    if isinstance(worker_input, dict):
        return str(worker_input.get("workerid") or "master")
    return "master"


def _build_wheelhouse(repo_root: Path, wheelhouse: Path) -> None:
    build_release.build_product_wheelhouse(
        repo_root=repo_root,
        wheelhouse=wheelhouse,
    )


def _write_product_wheelhouse_sentinel(wheelhouse: Path) -> None:
    payload = {
        "packages": list(PRODUCT_WHEELHOUSE_PACKAGES),
        "wheels": sorted(path.name for path in wheelhouse.glob("*.whl")),
    }
    (wheelhouse / ".built.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
