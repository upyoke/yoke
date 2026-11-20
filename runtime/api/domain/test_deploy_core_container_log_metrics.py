"""Declared observability.emit_log_metrics reaches the container and is proven.

The deploy writes YOKE_OTEL_LOG_METRICS=1 into the env file when the
environment declares log metrics, then fails if the new container started
without the EMF exporter (``instrumented_no_exporter``).
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.deploy_core_container_shared_test_support import (
    _BINDING,
    _HappyRemoteRunner,
    _env,
    patch_executor_boundaries,
)
from runtime.api.domain.deploy_remote_test_support import FakeRunner
from runtime.api.domain.test_deploy_environment_git_branch import (
    _full_capabilities,
    _prod_env,
    _settings,
)
from yoke_core.domain.deploy_core_container import (
    exec_core_container_deploy,
    render_service_files,
)
from yoke_core.domain.deploy_core_container_remote import (
    RemoteConvergenceError,
    verify_log_metrics_export,
)
from yoke_core.domain.deploy_environment_settings import (
    deploy_environment_from_settings,
)
from yoke_core.domain.deploy_remote import CommandResult

pytestmark = pytest.mark.windows


def _startup_line(reason: str) -> str:
    return json.dumps(
        {
            "level": "INFO",
            "event_name": "ObservabilityConfigured",
            "context": {"otel_enabled": True, "otel_reason": reason},
        }
    )


def _env_file(env) -> str:
    _compose, _nginx, env_file = render_service_files(
        env, env.image_ref("abc123def456"), _BINDING, repo_path=""
    )
    return env_file


@pytest.fixture
def pack_source(monkeypatch):
    patch_executor_boundaries(monkeypatch, _env())


class TestDeclaredSetting:
    @pytest.mark.parametrize(
        ("observability", "expected"),
        [({"emit_log_metrics": True}, True), ({"emit_log_metrics": False}, False), (None, False)],
    )
    def test_projects_onto_deploy_environment(self, observability, expected):
        overrides = {} if observability is None else {"observability": observability}
        env = deploy_environment_from_settings(
            _settings(
                environments=[_prod_env(**overrides)],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
        assert env.emit_log_metrics is expected


class TestContainerEnv:
    def test_flag_written_when_declared(self, pack_source):
        assert "YOKE_OTEL_LOG_METRICS=1\n" in _env_file(_env(emit_log_metrics=True))

    def test_flag_omitted_when_not_declared(self, pack_source):
        assert "YOKE_OTEL_LOG_METRICS" not in _env_file(_env(emit_log_metrics=False))


class TestExportCheck:
    def test_skipped_when_not_declared(self):
        runner = FakeRunner([])
        verify_log_metrics_export(runner, _env(), "yoke-core", lambda _l: None)
        assert runner.calls == []

    def test_passes_when_every_process_exports_log(self):
        lines = "\n".join([_startup_line("exporting:log")] * 2)
        runner = FakeRunner([CommandResult(0, lines + "\n", "")])
        emitted: list[str] = []
        verify_log_metrics_export(
            runner, _env(emit_log_metrics=True), "yoke-core", emitted.append
        )
        assert "docker logs yoke-core" in runner.calls[0]["argv"][-1]
        assert emitted == ["  [core-deploy] Yoke/API log metrics exporting (2 process(es))"]

    def test_fails_on_instrumented_no_exporter(self):
        lines = "\n".join(
            [_startup_line("exporting:log"), _startup_line("instrumented_no_exporter")]
        )
        runner = FakeRunner([CommandResult(0, lines, "")])
        with pytest.raises(RemoteConvergenceError) as exc:
            verify_log_metrics_export(
                runner, _env(emit_log_metrics=True), "yoke-core", lambda _l: None
            )
        message = str(exc.value)
        assert "instrumented_no_exporter" in message
        assert "YOKE_OTEL_LOG_METRICS=1" in message
        assert "redeploy" in message

    def test_fails_when_no_startup_record(self):
        runner = FakeRunner([CommandResult(0, "", "")])
        with pytest.raises(RemoteConvergenceError) as exc:
            verify_log_metrics_export(
                runner, _env(emit_log_metrics=True), "yoke-core", lambda _l: None
            )
        assert "no ObservabilityConfigured record" in str(exc.value)


class _StartupLogRunner(_HappyRemoteRunner):
    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason

    def run(self, argv, *, input_text=None, env=None, timeout=600):
        command = argv[-1] if argv and argv[0] == "ssh" else " ".join(argv)
        if command.startswith("docker logs yoke-core 2>&1 | grep"):
            self.calls.append({"argv": argv, "input_text": input_text})
            return CommandResult(0, _startup_line(self.reason) + "\n", "")
        return super().run(argv, input_text=input_text, env=env, timeout=timeout)


class TestDeployGate:
    def _deploy(self, monkeypatch, reason: str) -> tuple[int, list[str]]:
        patch_executor_boundaries(monkeypatch, _env(emit_log_metrics=True))
        runner = _StartupLogRunner(reason)
        rc = exec_core_container_deploy(
            "yoke", "prod", repo_path="/repo", runner=runner, emit=lambda _l: None
        )
        commands = [c["argv"][-1] for c in runner.calls if c["argv"][0] == "ssh"]
        return rc, commands

    def test_exporting_container_deploys(self, monkeypatch):
        rc, commands = self._deploy(monkeypatch, "exporting:log")
        assert rc == 0
        assert any(c.startswith("docker logs yoke-core 2>&1") for c in commands)

    def test_silent_exporter_loss_fails_without_rollback(self, monkeypatch, capsys):
        rc, commands = self._deploy(monkeypatch, "instrumented_no_exporter")
        assert rc == 1
        assert "instrumented_no_exporter" in capsys.readouterr().err
        assert not any("prior123" in c for c in commands)
