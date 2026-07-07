"""Shared pytest fixtures for repo-wide Yoke tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_core.tools import build_release


REPO_ROOT = Path(__file__).resolve().parent
PRODUCT_WHEELHOUSE_PACKAGES = build_release.PRODUCT_PACKAGE_NAMES


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
