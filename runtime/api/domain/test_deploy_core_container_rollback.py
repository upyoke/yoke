"""Tests for the core-deploy health-gate rollback (fake-runner plans)."""

from __future__ import annotations

import pytest

from yoke_core.domain import deploy_core_container_rollback as rollback_mod
from yoke_core.domain.deploy_core_container_rollback import (
    attempt_rollback,
    capture_running_image_ref,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.test_deploy_remote import FakeRunner

_PRIOR = "123456789012.dkr.ecr.us-east-1.amazonaws.com/yoke-core:prior123"
_FAILED = "123456789012.dkr.ecr.us-east-1.amazonaws.com/yoke-core:broken456"


def _env(**overrides) -> DeployEnvironment:
    values = dict(
        project="yoke",
        deploy_namespace="yoke",
        env_name="prod",
        site_id="yoke-api",
        api_host="api.example.com",
        origin_host="origin.example.com",
        origin_port=80,
        ssh_user="ubuntu",
        ssh_key_path="/keys/origin-example.pem",
        aws_region="us-east-1",
        aws_account_id="123456789012",
        repository_name="yoke-core",
        api_port=8765,
        health_path="/v1/health",
        stack_name="yoke-prod",
        activation_state="active",
        state_backend="s3://yoke-pulumi-state?region=us-east-1",
        database_name="yoke_prod",
    )
    values.update(overrides)
    return DeployEnvironment(**values)


class _PatternRunner(FakeRunner):
    """Answers remote commands by substring pattern; records every call."""

    def __init__(self, *, health_status: str = "healthy"):
        super().__init__()
        self.health_status = health_status

    def run(self, argv, *, input_text=None, env=None, timeout=600):
        self.calls.append(
            {"argv": list(argv), "input_text": input_text,
             "env": env, "timeout": timeout}
        )
        command = argv[-1] if argv and argv[0] == "ssh" else " ".join(argv)
        if "{{.State.Health.Status}}" in command:
            return CommandResult(0, f"{self.health_status}\n", "")
        if "docker logs" in command:
            return CommandResult(0, "rollback container logs", "")
        return CommandResult(0, "", "")


@pytest.fixture
def _events(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        rollback_mod,
        "_emit_rollback_event",
        lambda env, prior, failed, *, healthy: recorded.append(
            {"prior": prior, "failed": failed, "healthy": healthy}
        ),
    )
    return recorded


class TestCaptureRunningImageRef:
    def test_returns_stripped_ref_when_container_running(self):
        runner = FakeRunner([CommandResult(0, f"{_PRIOR}\n", "")])
        lines = []
        ref = capture_running_image_ref(runner, _env(), lines.append)
        assert ref == _PRIOR
        command = runner.calls[0]["argv"][-1]
        assert "{{.Config.Image}}" in command
        assert "yoke-core" in command
        assert any("pre-swap running image recorded" in line for line in lines)

    def test_returns_empty_on_probe_failure(self):
        runner = FakeRunner(
            [CommandResult(1, "", "No such object: yoke-core")]
        )
        lines = []
        ref = capture_running_image_ref(runner, _env(), lines.append)
        assert ref == ""
        assert any("rollback unavailable" in line for line in lines)

    def test_returns_empty_on_blank_stdout(self):
        runner = FakeRunner([CommandResult(0, "\n", "")])
        assert capture_running_image_ref(runner, _env(), lambda _l: None) == ""


class TestAttemptRollback:
    def _render_compose(self, ref: str) -> str:
        return f"services:\n  core:\n    image: {ref}\n"

    def test_no_prior_image_skips_with_note_and_no_event(self, _events):
        runner = _PatternRunner()
        lines = []
        ok = attempt_rollback(
            runner, _env(), prior_image_ref="", failed_image_ref=_FAILED,
            render_compose=self._render_compose, emit=lines.append,
        )
        assert ok is False
        assert runner.calls == []
        assert _events == []
        assert any("no pre-swap image was recorded" in line for line in lines)

    def test_same_image_skips_as_noop(self, _events):
        runner = _PatternRunner()
        lines = []
        ok = attempt_rollback(
            runner, _env(), prior_image_ref=_FAILED, failed_image_ref=_FAILED,
            render_compose=self._render_compose, emit=lines.append,
        )
        assert ok is False
        assert runner.calls == []
        assert _events == []
        assert any("no-op" in line for line in lines)

    def test_successful_rollback_repoints_compose_and_reports(self, _events):
        runner = _PatternRunner(health_status="healthy")
        lines = []
        ok = attempt_rollback(
            runner, _env(), prior_image_ref=_PRIOR, failed_image_ref=_FAILED,
            render_compose=self._render_compose, emit=lines.append,
        )
        assert ok is True
        compose_pushes = [
            c for c in runner.calls
            if c["argv"][-1].endswith(
                " /opt/yoke-core/docker-compose.yml 644"
            )
        ]
        assert len(compose_pushes) == 1
        assert _PRIOR in compose_pushes[0]["input_text"]
        assert _FAILED not in compose_pushes[0]["input_text"]
        joined = "\n".join(
            c["argv"][-1] for c in runner.calls if c["argv"][0] == "ssh"
        )
        assert "docker compose pull" in joined
        assert "docker compose up -d" in joined
        assert _events == [
            {"prior": _PRIOR, "failed": _FAILED, "healthy": True}
        ]
        assert any("still FAILED" in line for line in lines)

    def test_unhealthy_rollback_returns_false_never_raises(self, _events):
        runner = _PatternRunner(health_status="unhealthy")
        lines = []
        ok = attempt_rollback(
            runner, _env(), prior_image_ref=_PRIOR, failed_image_ref=_FAILED,
            render_compose=self._render_compose, emit=lines.append,
        )
        assert ok is False
        assert _events == [
            {"prior": _PRIOR, "failed": _FAILED, "healthy": False}
        ]
        assert any("did not converge" in line for line in lines)

    def test_compose_push_failure_returns_false_with_event(
        self, _events, monkeypatch,
    ):
        monkeypatch.setattr(
            rollback_mod,
            "push_remote_file",
            lambda *a, **kw: CommandResult(1, "", "disk full"),
        )
        runner = _PatternRunner()
        lines = []
        ok = attempt_rollback(
            runner, _env(), prior_image_ref=_PRIOR, failed_image_ref=_FAILED,
            render_compose=self._render_compose, emit=lines.append,
        )
        assert ok is False
        assert _events == [
            {"prior": _PRIOR, "failed": _FAILED, "healthy": False}
        ]
        assert any("rollback compose write failed" in line for line in lines)


class TestExecutorRollbackIntegration:
    """exec_core_container_deploy wires the rollback at the health gates."""

    def _setup(self, monkeypatch):
        from yoke_core.domain import deploy_core_container
        from runtime.api.domain.test_deploy_core_container import (
            patch_executor_boundaries,
        )

        env = _env()
        patch_executor_boundaries(monkeypatch, env)
        invocations = []

        def fake_rollback(runner, env_, *, prior_image_ref, failed_image_ref,
                          render_compose, emit):
            invocations.append(
                {"prior": prior_image_ref, "failed": failed_image_ref,
                 "compose": render_compose(prior_image_ref or "none")}
            )
            return False

        monkeypatch.setattr(
            deploy_core_container, "attempt_rollback", fake_rollback
        )
        return env, invocations

    def _unhealthy_runner(self):
        from runtime.api.domain.test_deploy_core_container import (
            _HappyRemoteRunner,
        )

        class UnhealthyRunner(_HappyRemoteRunner):
            """Post-swap health probe fails; everything else converges."""

            def run(self, argv, *, input_text=None, env=None, timeout=600):
                command = argv[-1] if argv and argv[0] == "ssh" else ""
                if "{{.State.Health.Status}}" in command:
                    self.calls.append({"argv": list(argv), "input_text": None,
                                       "env": env, "timeout": timeout})
                    return CommandResult(0, "unhealthy\n", "")
                if "docker logs" in command:
                    self.calls.append({"argv": list(argv), "input_text": None,
                                       "env": env, "timeout": timeout})
                    return CommandResult(0, "boom traceback", "")
                return super().run(argv, input_text=input_text, env=env,
                                   timeout=timeout)

        return UnhealthyRunner

    def test_unhealthy_container_rolls_back_and_fails(self, monkeypatch):
        from yoke_core.domain.deploy_core_container import (
            exec_core_container_deploy,
        )
        from runtime.api.domain.test_deploy_core_container import _PRIOR_IMAGE

        env, rollbacks = self._setup(monkeypatch)
        rc = exec_core_container_deploy(
            "yoke", "prod", repo_path="/repo",
            runner=self._unhealthy_runner()(), emit=lambda _line: None,
        )
        assert rc == 1
        # The post-swap health failure drove exactly one rollback attempt
        # to the pre-swap image; the stage still failed.
        assert len(rollbacks) == 1
        assert rollbacks[0]["prior"] == _PRIOR_IMAGE
        assert rollbacks[0]["failed"] == env.image_ref("abc123def456")
        assert f"image: {_PRIOR_IMAGE}" in rollbacks[0]["compose"]

    def test_first_deploy_no_prior_image_threads_empty_ref(self, monkeypatch):
        from yoke_core.domain.deploy_core_container import (
            exec_core_container_deploy,
        )

        env, rollbacks = self._setup(monkeypatch)
        base = self._unhealthy_runner()

        class FirstDeployUnhealthy(base):
            def run(self, argv, *, input_text=None, env=None, timeout=600):
                command = argv[-1] if argv and argv[0] == "ssh" else ""
                if "{{.Config.Image}}" in command:
                    self.calls.append({"argv": list(argv), "input_text": None,
                                       "env": env, "timeout": timeout})
                    return CommandResult(
                        1, "", "Error: No such object: yoke-core"
                    )
                return super().run(argv, input_text=input_text, env=env,
                                   timeout=timeout)

        rc = exec_core_container_deploy(
            "yoke", "prod", repo_path="/repo", runner=FirstDeployUnhealthy(),
            emit=lambda _line: None,
        )
        assert rc == 1
        # No prior image was recorded; the rollback helper is still called
        # and owns the explicit skip note.
        assert rollbacks and rollbacks[0]["prior"] == ""

    def test_pull_failure_does_not_attempt_rollback(self, monkeypatch):
        from yoke_core.domain.deploy_core_container import (
            exec_core_container_deploy,
        )
        from runtime.api.domain.test_deploy_core_container import (
            _HappyRemoteRunner,
        )

        env, rollbacks = self._setup(monkeypatch)

        class PullFails(_HappyRemoteRunner):
            def run(self, argv, *, input_text=None, env=None, timeout=600):
                command = argv[-1] if argv and argv[0] == "ssh" else ""
                if "docker compose pull" in command:
                    self.calls.append({"argv": list(argv), "input_text": None,
                                       "env": env, "timeout": timeout})
                    return CommandResult(1, "", "pull access denied")
                return super().run(argv, input_text=input_text, env=env,
                                   timeout=timeout)

        rc = exec_core_container_deploy(
            "yoke", "prod", repo_path="/repo", runner=PullFails(),
            emit=lambda _line: None,
        )
        assert rc == 1
        # The swap never completed — the old container is still running, so
        # no rollback fires for pre-swap failures.
        assert rollbacks == []

    def test_no_image_prune_on_rollback_path(self, monkeypatch):
        # The disk-reclaim prune runs only after a health-verified swap. When
        # the health gate fails and the deploy rolls back, no prune fires — the
        # prior image MUST survive on-box for the rollback to reach it.
        from yoke_core.domain.deploy_core_container import (
            exec_core_container_deploy,
        )

        env, rollbacks = self._setup(monkeypatch)
        runner = self._unhealthy_runner()()
        rc = exec_core_container_deploy(
            "yoke", "prod", repo_path="/repo", runner=runner,
            emit=lambda _line: None,
        )
        assert rc == 1
        assert len(rollbacks) == 1
        remote = [
            c["argv"][-1] for c in runner.calls
            if c["argv"] and c["argv"][0] == "ssh"
        ]
        assert not any("docker image prune" in c for c in remote)
