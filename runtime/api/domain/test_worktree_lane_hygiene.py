"""Stale lane bytecode is purged so a reused lane matches a clean checkout."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from yoke_core.domain.worktree_lane_hygiene import purge_lane_bytecode_caches
from yoke_core.domain.worktree_provision import provision_worktree_test_environment
from yoke_core.domain.worktree_test_environment import PROOF_DIRECTORY_NAME


def _import_value(root: Path) -> str:
    env = {**os.environ, "PYTHONPATH": str(root)}
    env.pop("SOURCE_DATE_EPOCH", None)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    result = subprocess.run(
        [sys.executable, "-c", "import victim; print(victim.VALUE)"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _plant_stale_bytecode(lane: Path) -> None:
    victim = lane / "victim.py"
    victim.write_text("VALUE = 'old'\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(lane)}
    env.pop("SOURCE_DATE_EPOCH", None)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    subprocess.run(
        [sys.executable, "-c", "import victim"],
        cwd=str(lane),
        env=env,
        check=True,
    )
    stat = victim.stat()
    victim.write_text("VALUE = 'new'\n", encoding="utf-8")
    os.utime(victim, (stat.st_atime, stat.st_mtime))


def test_stale_bytecode_diverges_until_hygiene_matches_the_clean_twin(
    tmp_path: Path,
) -> None:
    lane = tmp_path / "lane"
    clean = tmp_path / "clean"
    lane.mkdir()
    clean.mkdir()
    _plant_stale_bytecode(lane)
    (clean / "victim.py").write_text("VALUE = 'new'\n", encoding="utf-8")

    assert _import_value(lane) == "old"
    assert _import_value(clean) == "new"

    report = purge_lane_bytecode_caches(lane)

    assert report.purged_paths
    assert not (lane / "__pycache__").exists()
    assert _import_value(lane) == "new"
    assert _import_value(lane) == _import_value(clean)


def test_hygiene_leaves_source_and_the_venv_in_place(tmp_path: Path) -> None:
    lane = tmp_path / "lane"
    source = lane / "keep.py"
    venv_cfg = lane / ".venv" / "pyvenv.cfg"
    cache = lane / "pkg" / "__pycache__" / "mod.pyc"
    pytest_cache = lane / ".pytest_cache" / "v" / "cache" / "nodeids"
    proof = lane / PROOF_DIRECTORY_NAME / "test_lane_environment.py"
    for path in (source, venv_cfg, cache, pytest_cache, proof):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep\n", encoding="utf-8")

    report = purge_lane_bytecode_caches(lane)

    assert source.read_text(encoding="utf-8") == "keep\n"
    assert venv_cfg.read_text(encoding="utf-8") == "keep\n"
    assert not cache.exists()
    assert not pytest_cache.exists()
    assert not proof.exists()
    assert "__pycache__" in " ".join(report.purged_paths)
    assert ".pytest_cache" in " ".join(report.purged_paths)
    assert PROOF_DIRECTORY_NAME in " ".join(report.purged_paths)


def test_test_environment_provision_purges_before_the_lane_is_ready(
    tmp_path: Path,
) -> None:
    lane = tmp_path / "lane"
    lane.mkdir()
    _plant_stale_bytecode(lane)

    assert _import_value(lane) == "old"
    assert provision_worktree_test_environment(str(lane)) is None
    assert not (lane / "__pycache__").exists()
    assert _import_value(lane) == "new"
