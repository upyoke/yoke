"""Tests for the core-container-deploy step runner (fake-runner command plans)."""

from __future__ import annotations

import pytest

from runtime.api.domain.deploy_core_container_shared_test_support import (
    _BINDING as _BINDING,
    _HappyRemoteRunner as _HappyRemoteRunner,
    _PRIOR_IMAGE as _PRIOR_IMAGE,
    _env as _env,
    patch_executor_boundaries as patch_executor_boundaries,
)


from yoke_core.domain import deploy_core_container
from yoke_core.domain.deploy_core_container import (
    exec_core_container_deploy,
)
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.deploy_remote_test_support import FakeRunner


def _checked_in_project(tmp_path, stack: str):
    root = tmp_path / "project"
    (root / "infra").mkdir(parents=True)
    (root / "infra" / "Pulumi.yaml").write_text("name: webapp-infra\n")
    (root / "infra" / f"Pulumi.{stack}.yaml").write_text(
        "secretsprovider: awskms://alias/yoke-pulumi-state?region=us-east-1\n"
    )
    return root


class TestResolveEnvironmentDsn:
    def test_outputs_read_from_private_copy_of_checked_in_stack(
        self, tmp_path, monkeypatch
    ):
        from yoke_core.domain.deploy_core_container import (
            resolve_environment_dsn,
        )

        env = _env()
        project_root = _checked_in_project(tmp_path, env.stack_name)
        captured = {}

        def fake_outputs(infra_dir, location, env):
            captured["infra_dir"] = infra_dir
            captured["stack_file"] = (
                infra_dir / f"Pulumi.{location.stack}.yaml"
            ).read_text()
            return {"databaseClusterEndpoint": "ep", "databaseSecretArn": "arn"}

        monkeypatch.setattr(deploy_core_container, "load_stack_outputs", fake_outputs)
        monkeypatch.setattr(
            deploy_core_container,
            "load_secret_string",
            lambda arn, region, env: '{"username": "u", "password": "p", "port": 5432}',
        )
        runner = FakeRunner([CommandResult(0, "", "")])
        dsn, outputs = resolve_environment_dsn(
            runner, env, {}, repo_path=project_root, emit=lambda _l: None
        )
        assert captured["infra_dir"].name == "infra"
        assert captured["infra_dir"] != project_root / "infra"
        assert captured["stack_file"].startswith("secretsprovider: awskms://")
        assert not runner.calls
        assert "host=ep" in dsn and "dbname=yoke_prod" in dsn
        assert outputs["databaseClusterEndpoint"] == "ep"

    def test_missing_stack_file_refuses_with_recovery(self, tmp_path, monkeypatch):
        from yoke_core.domain.deploy_core_container import (
            CoreDeployError,
            resolve_environment_dsn,
        )

        monkeypatch.setattr(
            deploy_core_container,
            "load_stack_outputs",
            lambda *a, **k: pytest.fail("read outputs without a stack file"),
        )
        project_root = _checked_in_project(tmp_path, "some-other-stack")
        with pytest.raises(CoreDeployError, match="pulumi_stack_file_missing"):
            resolve_environment_dsn(
                FakeRunner([]), _env(), {}, repo_path=project_root,
                emit=lambda _l: None,
            )


class TestExecCoreContainerDeploy:
    def _patch_boundaries(self, monkeypatch, env):
        return patch_executor_boundaries(monkeypatch, env)

    def test_full_remote_plan_and_secret_hygiene(self, monkeypatch):
        env = _env()
        events = self._patch_boundaries(monkeypatch, env)
        runner = _HappyRemoteRunner()
        rc = exec_core_container_deploy(
            "yoke",
            "prod",
            repo_path="/repo",
            runner=runner,
            emit=lambda _line: None,
        )
        assert rc == 0
        assert events and events[0][0] == "prod"

        remote_commands = [c["argv"][-1] for c in runner.calls if c["argv"][0] == "ssh"]
        joined = "\n".join(remote_commands)
        assert "apt-get install" not in joined or "docker.io" in joined
        assert "awscli" not in joined
        assert "command -v aws" in joined
        assert "systemctl enable --now docker nginx" in joined
        assert "usermod -aG docker ubuntu" in joined
        assert "/etc/nginx/sites-available/yoke-core.conf" in joined
        assert "rm -f /etc/nginx/sites-enabled/default" in joined
        assert "docker compose pull" in joined
        assert "docker compose run --rm --no-deps --entrypoint python core" in joined
        assert "resolve_dsn_from_env" in joined
        assert "docker compose up -d --remove-orphans --force-recreate" in joined

        # Secret hygiene: the DB password never appears in argv or stdin. The
        # env file carries the managed secret ARN and endpoint facts only; the
        # runtime resolves the current password from Secrets Manager.
        all_argv = "\n".join(" ".join(c["argv"]) for c in runner.calls)
        all_stdin = "\n".join(str(c.get("input_text") or "") for c in runner.calls)
        assert "topsecret" not in all_argv
        assert "topsecret" not in all_stdin
        env_pushes = [
            c
            for c in runner.calls
            if c["argv"][0] == "ssh"
            and c["argv"][-1].endswith(" /opt/yoke-core/.env 600")
        ]
        assert len(env_pushes) == 1
        assert "YOKE_DB_SECRET_ARN=" in env_pushes[0]["input_text"]
        assert "YOKE_DB_HOST=db.internal" in env_pushes[0]["input_text"]
        dsn_pushes = [
            c
            for c in runner.calls
            if c["argv"][0] == "ssh"
            and c["argv"][-1].endswith(" /opt/yoke-core/dsn 444")
        ]
        assert dsn_pushes == []
        assert "chmod 700 /opt/yoke-core" in joined

    def test_declared_branch_threads_into_tag_resolution(self, monkeypatch):
        # The env's declared branch (environments.settings.git.branch)
        # reaches resolve_image_tag so persistent envs pin to branch HEAD.
        env = _env(git_branch="main")
        self._patch_boundaries(monkeypatch, env)
        seen = {}

        def fake_resolve(runner, repo, tag="", *, declared_branch=""):
            seen["declared_branch"] = declared_branch
            return "abc123def456"

        monkeypatch.setattr(deploy_core_container, "resolve_image_tag", fake_resolve)
        rc = exec_core_container_deploy(
            "yoke",
            "prod",
            repo_path="/repo",
            runner=_HappyRemoteRunner(),
            emit=lambda _line: None,
        )
        assert rc == 0
        assert seen["declared_branch"] == "main"

    def test_render_only_environment_refused(self, monkeypatch):
        env = _env(activation_state="render_only")
        self._patch_boundaries(monkeypatch, env)
        rc = exec_core_container_deploy(
            "yoke",
            "stage",
            repo_path="/repo",
            runner=FakeRunner(),
            emit=lambda _line: None,
        )
        assert rc == 1

    def test_prune_runs_after_successful_swap(self, monkeypatch):
        # A health-verified deploy reclaims disk from superseded images so the
        # origin box's small root volume never fills across repeated auto-
        # deploys. The prune runs AFTER the compose swap (post-success), so the
        # prior image survives the mid-deploy rollback window.
        env = _env()
        self._patch_boundaries(monkeypatch, env)
        runner = _HappyRemoteRunner()
        rc = exec_core_container_deploy(
            "yoke",
            "prod",
            repo_path="/repo",
            runner=runner,
            emit=lambda _line: None,
        )
        assert rc == 0
        remote = [c["argv"][-1] for c in runner.calls if c["argv"][0] == "ssh"]
        prune_idx = next(
            i for i, c in enumerate(remote) if c.startswith("python3 - --repository")
        )
        up_idx = next(i for i, c in enumerate(remote) if "docker compose up -d" in c)
        assert prune_idx > up_idx
        assert f"--keep {env.image_ref('abc123def456')}" in remote[prune_idx]
        assert not any("docker image prune --all" in command for command in remote)

    # Health-gate failure + rollback integration tests live in
    # test_deploy_core_container_rollback.py (TestStepRunnerRollbackIntegration),
    # which imports patch_executor_boundaries and _HappyRemoteRunner from here.
