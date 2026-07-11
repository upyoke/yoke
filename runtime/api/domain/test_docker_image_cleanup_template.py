"""Behavioral tests for repository-scoped Docker image cleanup."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "templates"
        / "webapp"
        / "ops"
        / "docker_image_cleanup.py"
    )
    spec = importlib.util.spec_from_file_location("docker_image_cleanup", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDocker:
    def __init__(
        self,
        *,
        images: dict[str, str],
        containers: dict[str, str] | None = None,
        remove_failures: dict[str, int] | None = None,
    ) -> None:
        self.images = dict(images)
        self.containers = dict(containers or {})
        self.remove_failures = dict(remove_failures or {})
        self.calls: list[tuple[str, ...]] = []

    @staticmethod
    def _result(returncode: int = 0, stdout: str = "", stderr: str = ""):
        return subprocess.CompletedProcess(
            ["docker"], returncode, stdout=stdout, stderr=stderr
        )

    def __call__(self, arguments):
        args = tuple(arguments)
        self.calls.append(args)
        if args == ("container", "ls", "--all", "--quiet"):
            return self._result(stdout="\n".join(self.containers) + "\n")
        if args[:4] == ("container", "inspect", "--format", "{{.Image}}"):
            return self._result(
                stdout="\n".join(self.containers[name] for name in args[4:]) + "\n"
            )
        if args[:4] == ("image", "inspect", "--format", "{{.Id}}"):
            reference = args[4]
            image_id = self.images.get(reference)
            if image_id is None:
                return self._result(1, stderr=f"No such image: {reference}")
            return self._result(stdout=image_id + "\n")
        if args[:6] == (
            "image",
            "ls",
            "--all",
            "--no-trunc",
            "--format",
            "{{.Repository}}\t{{.Tag}}\t{{.ID}}",
        ):
            repository = args[6]
            rows = []
            for reference, image_id in self.images.items():
                listed_repository, tag = reference.rsplit(":", 1)
                if listed_repository == repository:
                    rows.append(f"{listed_repository}\t{tag}\t{image_id}")
            return self._result(stdout="\n".join(rows) + ("\n" if rows else ""))
        if args[:2] == ("image", "rm"):
            reference = args[2]
            failures = self.remove_failures.get(reference, 0)
            if failures:
                self.remove_failures[reference] = failures - 1
                return self._result(1, stderr="temporary daemon failure")
            self.images.pop(reference, None)
            return self._result(stdout=f"Untagged: {reference}\n")
        raise AssertionError(f"unexpected fake Docker call: {args}")


@pytest.fixture(scope="module")
def cleanup_module() -> ModuleType:
    return _module()


def test_protects_container_images_and_explicit_future_pin(cleanup_module):
    repository = "registry.example.com/yoke-core"
    current = f"{repository}:current"
    old = f"{repository}:old"
    future = f"{repository}:future"
    unrelated = "registry.example.com/other:old"
    docker = FakeDocker(
        images={
            current: "sha256:current",
            old: "sha256:old",
            future: "sha256:future",
            unrelated: "sha256:unrelated",
        },
        containers={"running": "sha256:current"},
    )

    removed = cleanup_module.cleanup_repositories(
        [repository],
        keep_references=[future],
        runner=docker,
        pause=lambda _seconds: None,
        emit=lambda _line: None,
    )

    assert removed == 1
    assert old not in docker.images
    assert current in docker.images
    assert future in docker.images
    assert unrelated in docker.images
    assert ("image", "rm", current) not in docker.calls
    assert ("image", "rm", future) not in docker.calls


def test_transient_removal_failure_retries_idempotently(cleanup_module):
    repository = "registry.example.com/webapp"
    old = f"{repository}:old"
    docker = FakeDocker(images={old: "sha256:old"}, remove_failures={old: 2})
    pauses: list[float] = []

    removed = cleanup_module.cleanup_repositories(
        [repository],
        runner=docker,
        pause=pauses.append,
        emit=lambda _line: None,
    )

    assert removed == 1
    assert old not in docker.images
    assert pauses == [cleanup_module.RETRY_DELAY_SECONDS] * 2
    assert docker.calls.count(("image", "rm", old)) == 3


def test_persistent_removal_failure_is_visible(cleanup_module):
    repository = "registry.example.com/webapp"
    old = f"{repository}:old"
    docker = FakeDocker(images={old: "sha256:old"}, remove_failures={old: 3})

    with pytest.raises(cleanup_module.ImageCleanupError) as exc:
        cleanup_module.cleanup_repositories(
            [repository],
            runner=docker,
            pause=lambda _seconds: None,
            emit=lambda _line: None,
        )

    assert "after 3 attempts" in str(exc.value)
    assert old in docker.images


def test_missing_keep_fails_before_any_removal(cleanup_module):
    repository = "registry.example.com/yoke-core"
    old = f"{repository}:old"
    docker = FakeDocker(images={old: "sha256:old"})

    with pytest.raises(cleanup_module.ImageCleanupError) as exc:
        cleanup_module.cleanup_repositories(
            [repository],
            keep_references=[f"{repository}:missing"],
            runner=docker,
            pause=lambda _seconds: None,
            emit=lambda _line: None,
        )

    assert "explicitly protected Docker image is absent" in str(exc.value)
    assert not any(call[:2] == ("image", "rm") for call in docker.calls)
