"""Best-effort disk reclaim for self-hosted GitHub Actions runners."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time


DEFAULT_RUNNER_ROOT = Path("/opt/actions-runner")
DEFAULT_TMP_ROOT = Path("/tmp")
IMAGE_BUILDX_BUILDER = "yoke-core-builder"
STALE_TMP_MIN_AGE_SECONDS = 6 * 60 * 60


def _remove_path(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _truncate_file(path: Path) -> None:
    try:
        with path.open("w", encoding="utf-8"):
            pass
    except FileNotFoundError:
        return
    except OSError:
        return


def _path_age_seconds(path: Path, now: float) -> float | None:
    try:
        return now - path.stat().st_mtime
    except OSError:
        return None


def _remove_stale_runner_files(runner_root: Path) -> None:
    if not runner_root.is_dir():
        return
    for log in runner_root.glob("runner-*/_diag/*.log"):
        _truncate_file(log)


def _remove_stale_tmp_files(
    tmp_root: Path,
    *,
    min_age_seconds: int = STALE_TMP_MIN_AGE_SECONDS,
) -> None:
    if not tmp_root.is_dir():
        return
    now = time.time()
    for pattern in ("pip-*", "buildkit-*", "buildx-*", "docker-*"):
        for path in tmp_root.glob(pattern):
            age_seconds = _path_age_seconds(path, now)
            if age_seconds is None or age_seconds < min_age_seconds:
                continue
            _remove_path(path)


def _run_best_effort(args: list[str]) -> None:
    try:
        subprocess.run(args, check=False, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return


def _prune_docker() -> None:
    for args in (
        ["docker", "buildx", "rm", "-f", IMAGE_BUILDX_BUILDER],
        ["docker", "buildx", "prune", "-af"],
        ["docker", "builder", "prune", "-af"],
        ["docker", "system", "prune", "-af", "--volumes"],
        ["docker", "volume", "prune", "-f"],
    ):
        _run_best_effort(args)


def reclaim_runner_disk(
    *,
    runner_root: Path = DEFAULT_RUNNER_ROOT,
    tmp_root: Path = DEFAULT_TMP_ROOT,
) -> None:
    """Reclaim disposable runner disk without deleting the current checkout."""
    _remove_stale_runner_files(runner_root)
    _remove_stale_tmp_files(tmp_root)
    _prune_docker()


def main() -> int:
    for args in (
        ["df", "-h", "/", str(DEFAULT_TMP_ROOT), str(DEFAULT_RUNNER_ROOT)],
        ["docker", "system", "df"],
    ):
        _run_best_effort(args)
    reclaim_runner_disk()
    for args in (
        ["df", "-h", "/", str(DEFAULT_TMP_ROOT), str(DEFAULT_RUNNER_ROOT)],
        ["docker", "system", "df"],
    ):
        _run_best_effort(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["reclaim_runner_disk", "main"]
