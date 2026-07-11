from __future__ import annotations

import os
from pathlib import Path
import time

import pytest

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
    stale_log = diag / "Worker_old.log"
    stale_log.write_text("old log\n", encoding="utf-8")
    fresh_log = diag / "Worker_current.log"
    fresh_log.write_text("current log\n", encoding="utf-8")
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    stale_tmp = tmp_root / "pip-unpack-old"
    stale_tmp.mkdir()
    stale_mtime = time.time() - reclaim.STALE_TMP_MIN_AGE_SECONDS - 60
    os.utime(stale_tmp, (stale_mtime, stale_mtime))
    stale_log_mtime = (
        time.time() - reclaim.STALE_RUNNER_LOG_MIN_AGE_SECONDS - 60
    )
    os.utime(stale_log, (stale_log_mtime, stale_log_mtime))

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
    assert stale_log.read_text(encoding="utf-8") == ""
    assert fresh_log.read_text(encoding="utf-8") == "current log\n"
    # Generic temp prefixes are not ownership evidence on a persistent
    # multi-runner host, regardless of age.
    assert (tmp_root / "pip-unpack-old").is_dir()
    assert [
        "docker", "buildx", "prune", "-f", "--filter", "until=24h",
    ] in calls
    assert [
        "docker", "builder", "prune", "-f", "--filter", "until=24h",
    ] in calls
    assert ["docker", "image", "prune", "-f"] in calls
    assert not any(call[:3] == ["docker", "system", "prune"] for call in calls)
    assert not any(call[:3] == ["docker", "volume", "prune"] for call in calls)
    assert not any(
        call[:4] == ["docker", "image", "prune", "-af"] for call in calls
    )
    assert not any(call[:2] == ["sudo", "rm"] for call in calls)


def test_ephemeral_hosted_tmp_cleanup_preserves_recent_temp_dirs(
    tmp_path: Path,
) -> None:
    active_pip = tmp_path / "pip-build-tracker-active"
    active_buildkit = tmp_path / "buildkit-live"
    stale_pip = tmp_path / "pip-unpack-stale"
    unrelated = tmp_path / "pytest-current"
    for path in (active_pip, active_buildkit, stale_pip, unrelated):
        path.mkdir()
    stale_mtime = time.time() - 120
    os.utime(stale_pip, (stale_mtime, stale_mtime))

    reclaim._remove_ephemeral_hosted_tmp_files(
        tmp_path,
        min_age_seconds=60,
    )

    assert active_pip.is_dir()
    assert active_buildkit.is_dir()
    assert not stale_pip.exists()
    assert unrelated.is_dir()


def test_persistent_runner_preserves_old_generic_temp_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    generic_paths = [
        tmp_root / "pip-old",
        tmp_root / "buildkit-old",
        tmp_root / "buildx-old",
        tmp_root / "docker-old",
    ]
    stale_mtime = time.time() - reclaim.STALE_TMP_MIN_AGE_SECONDS - 60
    for path in generic_paths:
        path.mkdir()
        os.utime(path, (stale_mtime, stale_mtime))
    monkeypatch.setattr(reclaim.subprocess, "run", lambda *_args, **_kwargs: None)

    reclaim.reclaim_runner_disk(
        runner_root=tmp_path / "runner",
        tmp_root=tmp_root,
        runner_environment=reclaim.SELF_HOSTED,
    )

    assert all(path.is_dir() for path in generic_paths)


@pytest.mark.parametrize(
    ("runner_os", "environ", "message"),
    [
        ("macOS", {"GITHUB_ACTIONS": "true", "ImageOS": "ubuntu24"}, "Linux"),
        ("Linux", {"ImageOS": "ubuntu24"}, "GitHub Actions"),
        (
            "Linux",
            {
                "GITHUB_ACTIONS": "true",
                "RUNNER_ENVIRONMENT": "github-hosted",
                "RUNNER_OS": "Linux",
                "ImageOS": "custom-linux",
                "RUNNER_TOOL_CACHE": "/opt/hostedtoolcache",
            },
            "ImageOS",
        ),
        (
            "Linux",
            {
                "GITHUB_ACTIONS": "true",
                "RUNNER_ENVIRONMENT": "github-hosted",
                "RUNNER_OS": "Linux",
                "ImageOS": "ubuntu24",
            },
            "tool-cache",
        ),
        (
            "Linux",
            {
                "GITHUB_ACTIONS": "true",
                "RUNNER_ENVIRONMENT": "self-hosted",
                "RUNNER_OS": "Linux",
                "ImageOS": "ubuntu24",
                "RUNNER_TOOL_CACHE": "/opt/hostedtoolcache",
            },
            "RUNNER_ENVIRONMENT",
        ),
        (
            "Linux",
            {
                "GITHUB_ACTIONS": "true",
                "RUNNER_ENVIRONMENT": "github-hosted",
                "RUNNER_OS": "macOS",
                "ImageOS": "ubuntu24",
                "RUNNER_TOOL_CACHE": "/opt/hostedtoolcache",
            },
            "RUNNER_OS",
        ),
    ],
)
def test_hosted_cleanup_fails_closed_without_all_hosted_ubuntu_sentinels(
    runner_os: str,
    environ: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(reclaim.HostedRunnerCleanupRefused, match=message):
        reclaim.reclaim_runner_disk(
            runner_environment=reclaim.GITHUB_HOSTED,
            runner_os=runner_os,
            environ=environ,
            hosted_image_build_cleanup=True,
        )


def test_hosted_cleanup_removes_explicit_payloads_and_preserves_cache_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = tmp_path / "android"
    payload.mkdir()
    tool_cache = tmp_path / "hostedtoolcache"
    cached_python = tool_cache / "Python"
    cached_node = tool_cache / "node"
    cached_python.mkdir(parents=True)
    cached_node.mkdir()
    prefix_root = tmp_path / "usr-local"
    julia = prefix_root / "julia-1.12"
    unrelated = prefix_root / "bin"
    julia.mkdir(parents=True)
    unrelated.mkdir()
    monkeypatch.setattr(
        reclaim,
        "HOSTED_UBUNTU_DISPOSABLE_PATHS",
        (payload,),
    )
    monkeypatch.setattr(
        reclaim,
        "HOSTED_UBUNTU_DISPOSABLE_CONTENT_ROOTS",
        (tool_cache,),
    )
    monkeypatch.setattr(
        reclaim,
        "HOSTED_UBUNTU_DISPOSABLE_PREFIXES",
        ((prefix_root, "julia"),),
    )

    calls: list[list[str]] = []
    monkeypatch.setattr(
        reclaim.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(list(args)),
    )

    reclaim.reclaim_runner_disk(
        runner_root=tmp_path / "runner",
        tmp_root=tmp_path / "tmp",
        runner_environment=reclaim.GITHUB_HOSTED,
        runner_os="Linux",
        environ={
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "RUNNER_OS": "Linux",
            "ImageOS": "ubuntu24",
            "RUNNER_TOOL_CACHE": "/opt/hostedtoolcache",
        },
        hosted_image_build_cleanup=True,
    )

    privileged_removals = [
        call for call in calls if call[:5] == ["sudo", "-n", "rm", "-rf", "--"]
    ]
    assert [
        "sudo",
        "-n",
        "rm",
        "-rf",
        "--",
        str(payload),
    ] in privileged_removals
    assert [
        "sudo",
        "-n",
        "rm",
        "-rf",
        "--",
        str(cached_python),
    ] in privileged_removals
    assert [
        "sudo",
        "-n",
        "rm",
        "-rf",
        "--",
        str(cached_node),
    ] in privileged_removals
    assert [
        "sudo",
        "-n",
        "rm",
        "-rf",
        "--",
        str(julia),
    ] in privileged_removals
    assert ["sudo", "-n", "rm", "-rf", "--", str(tool_cache)] not in calls
    assert not any(str(unrelated) in call for call in calls)
    assert ["docker", "system", "prune", "-af", "--volumes"] in calls
    assert ["docker", "volume", "prune", "-f"] in calls


@pytest.mark.parametrize(
    ("runner_environment", "hosted_image_build_cleanup"),
    [
        (reclaim.SELF_HOSTED, True),
        (reclaim.GITHUB_HOSTED, False),
    ],
)
def test_privileged_cleanup_requires_hosted_runner_and_explicit_build_profile(
    runner_environment: str,
    hosted_image_build_cleanup: bool,
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        reclaim.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(list(args)),
    )

    reclaim.reclaim_runner_disk(
        runner_root=tmp_path / "runner",
        tmp_root=tmp_path / "tmp",
        runner_environment=runner_environment,
        runner_os="Linux",
        environ={
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "RUNNER_OS": "Linux",
            "ImageOS": "ubuntu24",
            "RUNNER_TOOL_CACHE": "/opt/hostedtoolcache",
        },
        hosted_image_build_cleanup=hosted_image_build_cleanup,
    )

    assert not any(call[:3] == ["sudo", "-n", "rm"] for call in calls)
    assert not any(call[:3] == ["docker", "system", "prune"] for call in calls)
    assert not any(call[:3] == ["docker", "volume", "prune"] for call in calls)
    assert ["docker", "image", "prune", "-f"] in calls


def test_invalid_runner_environment_is_rejected_before_any_cleanup(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        reclaim.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(list(args)),
    )

    with pytest.raises(ValueError, match="runner_environment"):
        reclaim.reclaim_runner_disk(runner_environment="unknown")

    assert calls == []
