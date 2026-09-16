"""Tests for the ephemeral-deploy step_runner (fake-runner command plans)."""

from __future__ import annotations

from pathlib import Path

from unittest import mock


from yoke_core.domain import deploy_ephemeral
from yoke_core.domain import deploy_ephemeral_files
from yoke_core.domain import deploy_ephemeral_remote as remote
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.test_deploy_remote import FakeRunner
from runtime.api.domain.deploy_ephemeral_test_support import (
    PORT as _PORT,
    SHA as _SHA,
    SLUG as _SLUG,
    env as _env,
    policy as _policy,
    install_ephemeral_project_source,
    scripted_runner as _scripted_runner,
)


class TestExecEphemeralDeploy:
    def test_full_deploy_command_plan(self, deploy_seams, monkeypatch, tmp_path):
        project_root = install_ephemeral_project_source(tmp_path)
        runner = _scripted_runner()
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        health_calls = []
        monkeypatch.setattr(
            "yoke_core.tools.step_runners.exec_health_check",
            lambda url, request_id="": health_calls.append(url) or 0,
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch=_SLUG,
            repo_path=str(project_root),
            item_label="YOK-9",
            runner=runner,
            emit=lambda _l: None,
        )
        assert rc == 0
        joined = [
            c["argv"][-1] if c["argv"][0] == "ssh" else " ".join(c["argv"])
            for c in runner.calls
        ]
        assert joined[0] == f"git -C {project_root} rev-parse {_SLUG}"
        bootstrap = next(c for c in joined if "environment_bootstrap" in c)
        assert "YOKE_DB_INIT_ALLOW=1" in bootstrap
        assert "docker compose run --rm" in bootstrap
        up = next(c for c in joined if "compose up" in c)
        assert "--force-recreate" in up and "--remove-orphans" in up
        health = next(c for c in joined if "curl" in c)
        assert f"127.0.0.1:{_PORT}/v1/health" in health
        # Public wildcard health check ran against the preview URL.
        assert health_calls == [f"https://{_SLUG}.preview.example.com/v1/health"]
        # Tracking: created with ports/url/sha, then flipped to running.
        first, last = deploy_seams.calls[0], deploy_seams.calls[-1]
        assert first[2]["port_api"] == str(_PORT)
        assert first[2]["deployed_sha"] == _SHA
        assert first[3] == "YOK-9"
        assert last[2]["status"] == "running"

    def test_existing_db_password_is_reused(self, deploy_seams, monkeypatch, tmp_path):
        project_root = install_ephemeral_project_source(tmp_path)
        runner = _scripted_runner()
        monkeypatch.setattr(deploy_ephemeral, "uuid", mock.Mock(uuid4=lambda: "RID"))
        monkeypatch.setattr(
            "yoke_core.tools.step_runners.exec_health_check",
            lambda url, request_id="": 0,
        )
        deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch=_SLUG,
            repo_path=str(project_root),
            runner=runner,
            emit=lambda _l: None,
        )
        pushes = [c for c in runner.calls if c["argv"][0] == "ssh" and c["input_text"]]
        password_push = next(c for c in pushes if "db-password" in c["argv"][-1])
        assert password_push["input_text"] == "cafe01\n"
        dsn_push = next(c for c in pushes if "/dsn" in c["argv"][-1])
        assert "password=cafe01" in dsn_push["input_text"]

    def test_branch_required(self, deploy_seams):
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch="",
            runner=FakeRunner(),
            emit=lambda _l: None,
        )
        assert rc == 1

    def test_render_only_host_env_refused(self, deploy_seams, monkeypatch, tmp_path):
        monkeypatch.setattr(
            deploy_ephemeral,
            "resolve_deploy_environment",
            lambda p, e: _env(activation_state="render_only"),
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch=_SLUG,
            repo_path=str(install_ephemeral_project_source(tmp_path)),
            runner=FakeRunner(),
            emit=lambda _l: None,
        )
        assert rc == 1

    def test_failure_marks_row_failed(self, deploy_seams, monkeypatch, tmp_path):
        runner = FakeRunner(
            [
                CommandResult(0, _SHA + "\n", ""),
                CommandResult(1, "", "ssh exploded"),  # tls probe
                CommandResult(1, "", "no certbot"),  # certbot pkg probe
                CommandResult(1, "", "apt broken"),  # certbot install -> fail
            ]
        )
        rc = deploy_ephemeral.exec_ephemeral_deploy(
            "yoke",
            branch=_SLUG,
            repo_path=str(install_ephemeral_project_source(tmp_path)),
            runner=runner,
            emit=lambda _l: None,
        )
        assert rc == 1
        assert deploy_seams.calls[-1][2] == {"status": "failed"}


class TestExecEphemeralTeardown:
    def test_teardown_command_plan(self, deploy_seams):
        runner = FakeRunner(
            [
                CommandResult(0, "", ""),  # compose down
                CommandResult(0, "", ""),  # rm -rf dir
            ]
        )
        rc = deploy_ephemeral.exec_ephemeral_teardown(
            "yoke",
            branch=_SLUG,
            runner=runner,
            emit=lambda _l: None,
        )
        assert rc == 0
        down = runner.calls[0]["argv"][-1]
        assert "docker compose down --volumes --remove-orphans" in down
        assert runner.calls[1]["argv"][-1] == (f"rm -rf ~/yoke-preview/{_SLUG}")
        assert deploy_seams.calls[-1][2] == {"status": "stopped"}

    def test_teardown_targets_source_preview_namespace_on_another_host_project(
        self, deploy_seams, monkeypatch
    ):
        monkeypatch.setattr(
            deploy_ephemeral,
            "load_ephemeral_policy",
            lambda p: _policy(project="yoke-next"),
        )
        monkeypatch.setattr(
            deploy_ephemeral,
            "resolve_deploy_environment",
            lambda p, e: _env(),
        )
        runner = FakeRunner(
            [
                CommandResult(0, "", ""),  # compose down
                CommandResult(0, "", ""),  # rm -rf dir
            ]
        )
        rc = deploy_ephemeral.exec_ephemeral_teardown(
            "yoke-next",
            branch=_SLUG,
            runner=runner,
            emit=lambda _l: None,
        )
        assert rc == 0
        down = runner.calls[0]["argv"][-1]
        assert f"docker compose -p yoke-preview-{_SLUG} down" in down
        assert runner.calls[1]["argv"][-1] == (f"rm -rf ~/yoke-preview/{_SLUG}")


class TestRemoteHelpers:
    def test_certbot_issued_only_when_cert_absent(self):
        runner = FakeRunner(
            [
                CommandResult(1, "", ""),  # cert probe -> absent
                CommandResult(0, "", ""),  # certbot packages present
                CommandResult(0, "", ""),  # certonly
            ]
        )
        remote.ensure_wildcard_tls(
            runner, _env(), "preview.example.com", lambda _l: None
        )
        issue = runner.calls[-1]["argv"][-1]
        assert 'certbot certonly --dns-route53 -d "*.preview.example.com"' in issue
        assert "--register-unsafely-without-email" in issue

    def test_dsn_pushed_world_readable_in_private_dir(self):
        runner = FakeRunner()
        remote.converge_slug_project(
            runner,
            _env(),
            "~/yoke-ephemeral/x",
            "compose",
            "envfile",
            "dsn-line",
            "cafe01",
            lambda _l: None,
        )
        prepare = runner.calls[0]["argv"][-1]
        assert "chmod 700 ~/yoke-ephemeral/x" in prepare
        dsn = next(c for c in runner.calls if "/dsn" in c["argv"][-1])["argv"][-1]
        assert "os.replace" in dsn
        assert dsn.endswith("/dsn 444")

    def test_password_hex_guard_rejects_garbage(self):
        runner = FakeRunner([CommandResult(0, "not hex!\n", "")])
        value = remote.read_existing_db_password(runner, _env(), "~/yoke-ephemeral/x")
        assert value == ""


def test_slug_files_name_database_by_preview_namespace(monkeypatch):
    monkeypatch.setattr(
        deploy_ephemeral_files,
        "render_webapp_template",
        lambda _root, _relative, _values: "compose-yaml",
    )
    policy = _policy()
    env = _env()

    _compose, _env_file, dsn = deploy_ephemeral_files.slug_files(
        policy,
        env,
        "my-slug",
        "img:tag",
        9100,
        "deadbeef",
        project_root=Path("/project"),
    )

    assert "dbname=yoke_preview user=yoke_preview" in dsn
    assert "platform" not in dsn
