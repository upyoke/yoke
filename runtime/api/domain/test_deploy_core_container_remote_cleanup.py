"""Tests for post-health image cleanup on persistent core hosts."""

from __future__ import annotations

import pytest

from runtime.api.domain.deploy_core_container_test_support import (
    install_core_service_project_source,
)
from runtime.api.domain.test_deploy_core_container import (
    _env,
)
from runtime.api.domain.test_deploy_remote import FakeRunner
from yoke_core.domain.deploy_core_container_remote import (
    RemoteConvergenceError,
    prune_superseded_images,
)
from yoke_core.domain.deploy_core_container_remote_cleanup import _cleanup_program
from yoke_core.domain.deploy_remote import CommandResult


class TestPruneSupersededImages:
    def test_cleanup_program_uses_project_owned_pack_file(self, tmp_path):
        project_root = install_core_service_project_source(tmp_path)
        program = project_root / "ops" / "docker_image_cleanup.py"
        program.write_text("print('project copy')\n", encoding="utf-8")

        assert _cleanup_program(project_root) == "print('project copy')\n"

    def test_runs_repository_scoped_cleanup_with_explicit_keep(self, tmp_path):
        runner = FakeRunner(
            [CommandResult(0, "image cleanup: complete (2 superseded tags removed)\n", "")]
        )
        lines: list[str] = []
        env = _env()
        keep = env.image_ref("abc123")
        prune_superseded_images(
            runner,
            env,
            lines.append,
            keep_image_ref=keep,
            project_root=install_core_service_project_source(tmp_path),
        )

        command = runner.calls[0]["argv"][-1]
        assert "python3 - --repository" in command
        assert f"--repository {env.registry_host}/{env.repository_name}" in command
        assert f"--keep {keep}" in command
        assert "prune --all" not in command
        assert "cleanup_repositories" in runner.calls[0]["input_text"]
        assert any("2 superseded tags removed" in line for line in lines)

    def test_transient_failure_retries_then_succeeds(self, tmp_path):
        runner = FakeRunner(
            [
                CommandResult(1, "", "Cannot connect to the Docker daemon"),
                CommandResult(
                    0,
                    "image cleanup: complete (1 superseded tag removed)\n",
                    "",
                ),
            ]
        )
        lines: list[str] = []
        env = _env()
        prune_superseded_images(
            runner,
            env,
            lines.append,
            keep_image_ref=env.image_ref("abc123"),
            project_root=install_core_service_project_source(tmp_path),
        )

        assert len(runner.calls) == 2
        assert any("attempt 1/3 failed" in line for line in lines)
        assert any("1 superseded tag removed" in line for line in lines)

    def test_persistent_failure_is_visible(self, tmp_path):
        runner = FakeRunner(
            [CommandResult(1, "", "Cannot connect to the Docker daemon")] * 3
        )
        lines: list[str] = []

        with pytest.raises(RemoteConvergenceError) as exc:
            env = _env()
            prune_superseded_images(
                runner,
                env,
                lines.append,
                keep_image_ref=env.image_ref("abc123"),
                project_root=install_core_service_project_source(tmp_path),
            )

        assert len(runner.calls) == 3
        assert "image cleanup failed after 3 attempts" in str(exc.value)
        assert "rerun the idempotent deploy" in str(exc.value)

    def test_runner_exception_is_retried_then_visible(self, tmp_path):
        class Boom(FakeRunner):
            def run(self, argv, *, input_text=None, env=None, timeout=600):
                raise RuntimeError("ssh blew up")

        lines: list[str] = []
        with pytest.raises(RemoteConvergenceError) as exc:
            env = _env()
            prune_superseded_images(
                Boom(),
                env,
                lines.append,
                keep_image_ref=env.image_ref("abc123"),
                project_root=install_core_service_project_source(tmp_path),
            )

        assert "RuntimeError" in str(exc.value)
        assert sum("retrying" in line for line in lines) == 2
