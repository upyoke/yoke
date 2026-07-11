"""Best-effort disk reclaim for GitHub Actions runners.

Persistent self-hosted runners receive the conservative recurring cleanup.
Ephemeral GitHub-hosted Ubuntu runners may additionally discard the large
preinstalled SDK and browser payloads that Yoke's Python/Docker jobs do not
consume.  That broader cleanup is fail-closed behind explicit runner metadata
plus the GitHub-hosted image sentinels.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import shutil
import subprocess
import time


DEFAULT_RUNNER_ROOT = Path("/opt/actions-runner")
DEFAULT_TMP_ROOT = Path("/tmp")
IMAGE_BUILDX_BUILDER = "yoke-core-builder"
STALE_TMP_MIN_AGE_SECONDS = 6 * 60 * 60
STALE_RUNNER_LOG_MIN_AGE_SECONDS = 24 * 60 * 60
GITHUB_HOSTED = "github-hosted"
SELF_HOSTED = "self-hosted"

# These payloads are installed on GitHub-hosted Ubuntu images but are not used
# by Yoke's Python/Docker workflows.  Removing them is appropriate only on an
# ephemeral hosted VM.  Keep the list explicit: never derive privileged delete
# targets from environment variables or caller-controlled paths.
HOSTED_UBUNTU_DISPOSABLE_PATHS = (
    Path("/home/linuxbrew"),
    Path("/home/runner/.cache"),
    Path("/home/runner/.cargo"),
    Path("/home/runner/.nvm"),
    Path("/home/runner/.rustup"),
    Path("/opt/actionarchivecache"),
    Path("/opt/az"),
    Path("/opt/ghc"),
    Path("/opt/google"),
    Path("/opt/google-cloud-sdk"),
    Path("/opt/microsoft"),
    Path("/opt/pipx"),
    Path("/opt/pipx_bin"),
    Path("/usr/lib/firefox"),
    Path("/usr/lib/google-cloud-sdk"),
    Path("/usr/lib/jvm"),
    Path("/usr/lib/R"),
    Path("/usr/local/.ghcup"),
    Path("/usr/local/aws-sam-cli"),
    Path("/usr/local/cuda"),
    Path("/usr/local/lib/android"),
    Path("/usr/local/lib/node_modules"),
    Path("/usr/local/lib/R"),
    Path("/usr/local/share/boost"),
    Path("/usr/local/share/chromium"),
    Path("/usr/local/share/powershell"),
    Path("/usr/local/share/vcpkg"),
    Path("/usr/share/dotnet"),
    Path("/usr/share/doc"),
    Path("/usr/share/info"),
    Path("/usr/share/man"),
    Path("/usr/share/miniconda"),
    Path("/usr/share/R"),
    Path("/usr/share/swift"),
)

# Preserve the cache root itself so later setup-* actions can repopulate it
# without needing to recreate a root-owned directory.
HOSTED_UBUNTU_DISPOSABLE_CONTENT_ROOTS = (
    Path("/opt/hostedtoolcache"),
    Path("/var/cache/apt/archives"),
    Path("/var/lib/apt/lists"),
)
HOSTED_UBUNTU_DISPOSABLE_PREFIXES = (
    (Path("/usr/lib"), "llvm-"),
    (Path("/usr/local"), "cuda-"),
    (Path("/usr/local"), "julia"),
)


class HostedRunnerCleanupRefused(RuntimeError):
    """Raised when broad hosted-runner cleanup lacks trusted sentinels."""


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


def _remove_stale_runner_files(
    runner_root: Path,
    *,
    min_age_seconds: int = STALE_RUNNER_LOG_MIN_AGE_SECONDS,
) -> None:
    """Truncate only old, runner-owned diagnostics.

    A persistent host can run several workers at once. Directory ownership is
    not evidence that a log is inactive, so fresh/current diagnostics remain
    intact and only files whose mtime has crossed the explicit retention
    threshold are reclaimed.
    """
    if not runner_root.is_dir():
        return
    now = time.time()
    for log in runner_root.glob("runner-*/_diag/*.log"):
        age_seconds = _path_age_seconds(log, now)
        if age_seconds is None or age_seconds < min_age_seconds:
            continue
        _truncate_file(log)


def _remove_ephemeral_hosted_tmp_files(
    tmp_root: Path,
    *,
    min_age_seconds: int = STALE_TMP_MIN_AGE_SECONDS,
) -> None:
    """Remove generic build temp paths only on a verified ephemeral VM.

    Callers must first pass ``_assert_hosted_ubuntu_cleanup_authority``. These
    prefixes are not ownership evidence on a persistent multi-runner host,
    where even an old path may belong to another active or paused job.
    """
    if not tmp_root.is_dir():
        return
    now = time.time()
    for pattern in ("pip-*", "buildkit-*", "buildx-*", "docker-*"):
        for path in tmp_root.glob(pattern):
            age_seconds = _path_age_seconds(path, now)
            if age_seconds is None or age_seconds < min_age_seconds:
                continue
            _remove_path(path)


def _run_best_effort(args: Sequence[str]) -> None:
    try:
        subprocess.run(list(args), check=False, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return


def _prune_docker(*, aggressive_hosted: bool) -> None:
    """Reclaim Docker state without crossing persistent-host boundaries."""
    if aggressive_hosted:
        commands = (
            ["docker", "buildx", "rm", "-f", IMAGE_BUILDX_BUILDER],
            ["docker", "buildx", "prune", "-af"],
            ["docker", "builder", "prune", "-af"],
            ["docker", "system", "prune", "-af", "--volumes"],
            ["docker", "volume", "prune", "-f"],
        )
    else:
        # Persistent runners may hold tagged prewarmed images and unrelated
        # volumes between jobs. Limit recurring cleanup to old builder cache
        # and dangling images; neither operation removes tagged image refs,
        # container-owned images, or named volumes.
        commands = (
            ["docker", "buildx", "prune", "-f", "--filter", "until=24h"],
            ["docker", "builder", "prune", "-f", "--filter", "until=24h"],
            ["docker", "image", "prune", "-f"],
        )
    for args in commands:
        _run_best_effort(args)


def _assert_hosted_ubuntu_cleanup_authority(
    *,
    runner_os: str,
    environ: Mapping[str, str],
) -> None:
    if runner_os != "Linux":
        raise HostedRunnerCleanupRefused(
            "broad runner cleanup requires runner.os=Linux"
        )
    if environ.get("GITHUB_ACTIONS", "").lower() != "true":
        raise HostedRunnerCleanupRefused(
            "broad runner cleanup is allowed only inside GitHub Actions"
        )
    if environ.get("RUNNER_ENVIRONMENT") != GITHUB_HOSTED:
        raise HostedRunnerCleanupRefused(
            "broad runner cleanup requires RUNNER_ENVIRONMENT=github-hosted"
        )
    if environ.get("RUNNER_OS") != "Linux":
        raise HostedRunnerCleanupRefused(
            "broad runner cleanup requires RUNNER_OS=Linux"
        )
    image_os = environ.get("ImageOS", "").lower()
    if not image_os.startswith("ubuntu"):
        raise HostedRunnerCleanupRefused(
            "broad runner cleanup requires the GitHub-hosted Ubuntu ImageOS sentinel"
        )
    if environ.get("RUNNER_TOOL_CACHE") != "/opt/hostedtoolcache":
        raise HostedRunnerCleanupRefused(
            "broad runner cleanup requires the GitHub-hosted tool-cache sentinel"
        )


def _remove_privileged_path(path: Path) -> None:
    print(f"removing hosted-runner payload: {path}")
    _run_best_effort(["sudo", "-n", "rm", "-rf", "--", str(path)])


def _remove_privileged_contents(root: Path) -> None:
    try:
        if root.is_symlink() or not root.is_dir():
            return
        children = tuple(root.iterdir())
    except OSError:
        return
    for child in children:
        _remove_privileged_path(child)


def _remove_privileged_prefixes(root: Path, prefix: str) -> None:
    try:
        if root.is_symlink() or not root.is_dir():
            return
        matches = tuple(
            child for child in root.iterdir() if child.name.startswith(prefix)
        )
    except OSError:
        return
    for path in matches:
        _remove_privileged_path(path)


def _reclaim_hosted_ubuntu_payloads(
    *,
    runner_os: str,
    environ: Mapping[str, str],
) -> None:
    _assert_hosted_ubuntu_cleanup_authority(
        runner_os=runner_os,
        environ=environ,
    )
    for path in HOSTED_UBUNTU_DISPOSABLE_PATHS:
        _remove_privileged_path(path)
    for root in HOSTED_UBUNTU_DISPOSABLE_CONTENT_ROOTS:
        _remove_privileged_contents(root)
    for root, prefix in HOSTED_UBUNTU_DISPOSABLE_PREFIXES:
        _remove_privileged_prefixes(root, prefix)


def reclaim_runner_disk(
    *,
    runner_root: Path = DEFAULT_RUNNER_ROOT,
    tmp_root: Path = DEFAULT_TMP_ROOT,
    runner_environment: str = SELF_HOSTED,
    runner_os: str = "",
    environ: Mapping[str, str] | None = None,
    hosted_image_build_cleanup: bool = False,
) -> None:
    """Reclaim disposable runner disk without deleting the current checkout."""
    if runner_environment not in (GITHUB_HOSTED, SELF_HOSTED):
        raise ValueError("runner_environment must be 'github-hosted' or 'self-hosted'")
    aggressive_hosted = (
        hosted_image_build_cleanup and runner_environment == GITHUB_HOSTED
    )
    if aggressive_hosted:
        _reclaim_hosted_ubuntu_payloads(
            runner_os=runner_os,
            environ=os.environ if environ is None else environ,
        )
        _remove_ephemeral_hosted_tmp_files(tmp_root)
    _remove_stale_runner_files(runner_root)
    _prune_docker(aggressive_hosted=aggressive_hosted)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runner-environment",
        choices=(GITHUB_HOSTED, SELF_HOSTED),
        default=SELF_HOSTED,
        help=(
            "GitHub runner.environment value. The broad hosted cleanup is "
            "disabled unless github-hosted is passed explicitly."
        ),
    )
    parser.add_argument(
        "--runner-os",
        default="",
        help="GitHub runner.os value; Linux is required for hosted cleanup.",
    )
    parser.add_argument(
        "--hosted-image-build-cleanup",
        action="store_true",
        help=(
            "Discard unused SDK/browser payloads on an explicitly verified "
            "ephemeral GitHub-hosted Ubuntu image builder."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    parsed = _parse_args(argv)
    for command in (
        ["df", "-h", "/", str(DEFAULT_TMP_ROOT), str(DEFAULT_RUNNER_ROOT)],
        ["docker", "system", "df"],
    ):
        _run_best_effort(command)
    reclaim_runner_disk(
        runner_environment=parsed.runner_environment,
        runner_os=parsed.runner_os,
        hosted_image_build_cleanup=parsed.hosted_image_build_cleanup,
    )
    for command in (
        ["df", "-h", "/", str(DEFAULT_TMP_ROOT), str(DEFAULT_RUNNER_ROOT)],
        ["docker", "system", "df"],
    ):
        _run_best_effort(command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["reclaim_runner_disk", "main"]
