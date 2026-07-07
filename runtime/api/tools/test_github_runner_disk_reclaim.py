from __future__ import annotations

import os
from pathlib import Path
import time

from yoke_core.tools import github_runner_disk_reclaim as reclaim


def test_reclaim_preserves_runner_work_dirs_and_removes_stale_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner_root = tmp_path / "actions-runner"
    current_workspace = runner_root / "runner-1" / "_work" / "yoke" / "yoke"
    current_workspace.mkdir(parents=True)
    (current_workspace / "kept.txt").write_text("keep\n", encoding="utf-8")
    stale_work = runner_root / "runner-1" / "_work" / "old-checkout"
    stale_work.mkdir()
    (stale_work / "old.txt").write_text("old\n", encoding="utf-8")
    action_cache = runner_root / "runner-1" / "_work" / "_actions"
    action_cache.mkdir()
    (action_cache / "action.yml").write_text("name: cached action\n", encoding="utf-8")
    diag = runner_root / "runner-1" / "_diag"
    diag.mkdir()
    (diag / "Worker_old.log").write_text("old log\n", encoding="utf-8")
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    stale_tmp = tmp_root / "pip-unpack-old"
    stale_tmp.mkdir()
    stale_mtime = time.time() - reclaim.STALE_TMP_MIN_AGE_SECONDS - 60
    os.utime(stale_tmp, (stale_mtime, stale_mtime))

    calls: list[list[str]] = []
    monkeypatch.setattr(
        reclaim.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(list(args)),
    )

    reclaim.reclaim_runner_disk(runner_root=runner_root, tmp_root=tmp_root)

    assert (current_workspace / "kept.txt").is_file()
    assert (action_cache / "action.yml").is_file()
    assert (stale_work / "old.txt").is_file()
    assert (diag / "Worker_old.log").read_text(encoding="utf-8") == ""
    assert not (tmp_root / "pip-unpack-old").exists()
    assert ["docker", "buildx", "rm", "-f", "yoke-core-builder"] in calls
    assert ["docker", "system", "prune", "-af", "--volumes"] in calls


def test_tmp_cleanup_preserves_active_temp_dirs(tmp_path: Path) -> None:
    active_pip = tmp_path / "pip-build-tracker-active"
    active_buildkit = tmp_path / "buildkit-live"
    stale_pip = tmp_path / "pip-unpack-stale"
    unrelated = tmp_path / "pytest-current"
    for path in (active_pip, active_buildkit, stale_pip, unrelated):
        path.mkdir()
    stale_mtime = time.time() - 120
    os.utime(stale_pip, (stale_mtime, stale_mtime))

    reclaim._remove_stale_tmp_files(tmp_path, min_age_seconds=60)

    assert active_pip.is_dir()
    assert active_buildkit.is_dir()
    assert not stale_pip.exists()
    assert unrelated.is_dir()
