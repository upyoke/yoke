"""Tests for image artifact resolution (tag pin + registry ensure)."""

from __future__ import annotations


import pytest

from yoke_core.domain import project_scratch_dir
from yoke_core.domain.deploy_core_container_image import (
    IMAGE_WAIT_ENV_VAR,
    CoreDeployError,
    ensure_image_in_registry,
    resolve_image_tag,
)
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.test_deploy_core_container import _env
from runtime.api.domain.test_deploy_remote import FakeRunner

_ABSENT = CommandResult(1, "", "ImageNotFoundException")


class TestResolveImageTag:
    def test_explicit_tag_wins(self):
        assert resolve_image_tag(FakeRunner(), "/repo", "pinned") == "pinned"

    def test_explicit_tag_wins_over_declared_branch(self):
        # Break-glass override beats the env's declared branch; no git
        # commands run at all.
        runner = FakeRunner()
        tag = resolve_image_tag(
            runner, "/repo", "pinned", declared_branch="stage"
        )
        assert tag == "pinned"
        assert runner.calls == []

    def test_head_sha_short_form(self):
        runner = FakeRunner(
            [CommandResult(0, "abcdef0123456789abcdef0123456789abcdef01\n", "")]
        )
        assert resolve_image_tag(runner, "/repo") == "abcdef012345"
        assert runner.calls[0]["argv"] == [
            "git", "-C", "/repo", "rev-parse", "HEAD",
        ]

    def test_declared_branch_pins_to_fetched_remote_head(self):
        # Declared-branch envs deploy origin/<branch> HEAD via fetch +
        # FETCH_HEAD — never ambient checkout HEAD.
        runner = FakeRunner(
            [
                CommandResult(0, "", ""),  # git fetch origin stage
                CommandResult(
                    0, "1234567890abcdef1234567890abcdef12345678\n", ""
                ),  # git rev-parse FETCH_HEAD
            ]
        )
        tag = resolve_image_tag(runner, "/repo", declared_branch="stage")
        assert tag == "1234567890ab"
        assert runner.calls[0]["argv"] == [
            "git", "-C", "/repo", "fetch", "origin", "stage",
        ]
        assert runner.calls[1]["argv"] == [
            "git", "-C", "/repo", "rev-parse", "FETCH_HEAD",
        ]

    def test_declared_branch_fetch_failure_is_loud(self):
        runner = FakeRunner(
            [CommandResult(1, "", "fatal: couldn't find remote ref stage")]
        )
        with pytest.raises(CoreDeployError, match="declared branch 'stage'"):
            resolve_image_tag(runner, "/repo", declared_branch="stage")

    def test_no_repo_and_no_tag_fails(self):
        with pytest.raises(CoreDeployError):
            resolve_image_tag(FakeRunner(), "", "")


class TestEnsureImageInRegistry:
    def test_present_image_skips_build(self):
        runner = FakeRunner([CommandResult(0, "{}", "")])
        ref = ensure_image_in_registry(
            runner, _env(), {"AWS_REGION": "us-east-1"},
            repo_path="/repo", tag="abc123", emit=lambda _line: None,
        )
        assert ref.endswith("yoke-core:abc123")
        assert len(runner.calls) == 1
        assert runner.calls[0]["argv"][:3] == ["aws", "ecr", "describe-images"]

    def test_absent_image_builds_logs_in_and_pushes(self, tmp_path):
        runner = FakeRunner(
            [
                CommandResult(1, "", "ImageNotFoundException"),  # describe
                CommandResult(0, "", ""),  # git archive
                CommandResult(0, "", ""),  # tar extract
                CommandResult(0, "", ""),  # docker build
                CommandResult(0, "ecr-token\n", ""),  # get-login-password
                CommandResult(0, "", ""),  # docker login
                CommandResult(0, "", ""),  # docker push
            ]
        )
        ref = ensure_image_in_registry(
            runner, _env(), {"AWS_REGION": "us-east-1"},
            repo_path="/repo", tag="abc123", emit=lambda _line: None,
            build_dir=tmp_path,
        )
        argvs = [c["argv"] for c in runner.calls]
        assert argvs[1][:4] == ["git", "-C", "/repo", "archive"]
        assert argvs[3][:2] == ["docker", "build"]
        assert "--platform" in argvs[3] and "linux/arm64" in argvs[3]
        # The image bakes its own provenance: /v1/health serves this sha.
        assert "YOKE_BUILD_SHA=abc123" in argvs[3]
        assert argvs[4] == ["aws", "ecr", "get-login-password"]
        login_call = runner.calls[5]
        assert login_call["argv"][:2] == ["docker", "login"]
        assert login_call["input_text"] == "ecr-token"
        assert "ecr-token" not in " ".join(login_call["argv"])
        assert argvs[6] == ["docker", "push", ref]

    def test_build_failure_surfaces_error(self, tmp_path):
        runner = FakeRunner(
            [
                CommandResult(1, "", "not found"),
                CommandResult(0, "", ""),
                CommandResult(0, "", ""),
                CommandResult(1, "", "Dockerfile syntax error"),
            ]
        )
        with pytest.raises(CoreDeployError) as exc:
            ensure_image_in_registry(
                runner, _env(), {},
                repo_path="/repo", tag="abc", emit=lambda _line: None,
                build_dir=tmp_path,
            )
        assert "docker build failed" in str(exc.value)

    def test_helper_owned_build_workspace_is_removed_after_success(
        self, tmp_path, monkeypatch
    ):
        owned = tmp_path / "helper-owned"
        monkeypatch.setattr(
            project_scratch_dir,
            "storage_dir",
            lambda *_args, **_kwargs: owned,
        )
        runner = FakeRunner(
            [
                _ABSENT,
                CommandResult(0, "", ""),
                CommandResult(0, "", ""),
                CommandResult(0, "", ""),
                CommandResult(0, "ecr-token\n", ""),
                CommandResult(0, "", ""),
                CommandResult(0, "", ""),
            ]
        )

        ensure_image_in_registry(
            runner,
            _env(),
            {"AWS_REGION": "us-east-1"},
            repo_path="/repo",
            tag="abc123",
            emit=lambda _line: None,
        )

        assert not owned.exists()

    def test_helper_owned_build_workspace_is_removed_after_failure(
        self, tmp_path, monkeypatch
    ):
        owned = tmp_path / "helper-owned"
        monkeypatch.setattr(
            project_scratch_dir,
            "storage_dir",
            lambda *_args, **_kwargs: owned,
        )
        runner = FakeRunner(
            [
                _ABSENT,
                CommandResult(0, "", ""),
                CommandResult(0, "", ""),
                CommandResult(1, "", "Dockerfile syntax error"),
            ]
        )

        with pytest.raises(CoreDeployError, match="docker build failed"):
            ensure_image_in_registry(
                runner,
                _env(),
                {},
                repo_path="/repo",
                tag="abc123",
                emit=lambda _line: None,
            )

        assert not owned.exists()

    def test_explicit_diagnostic_build_workspace_is_preserved(self, tmp_path):
        diagnostic = tmp_path / "diagnostic"
        runner = FakeRunner(
            [
                _ABSENT,
                CommandResult(0, "", ""),
                CommandResult(0, "", ""),
                CommandResult(1, "", "Dockerfile syntax error"),
            ]
        )

        with pytest.raises(CoreDeployError, match="docker build failed"):
            ensure_image_in_registry(
                runner,
                _env(),
                {},
                repo_path="/repo",
                tag="abc123",
                emit=lambda _line: None,
                build_dir=diagnostic,
            )

        assert diagnostic.is_dir()
        assert (diagnostic / "src").is_dir()


class TestEnsureImageWaitMode:
    """YOKE_DEPLOY_IMAGE_WAIT=1 — wait for the prewarm, never build."""

    def test_polls_until_prewarmed_image_appears(self, monkeypatch):
        monkeypatch.setenv(IMAGE_WAIT_ENV_VAR, "1")
        runner = FakeRunner(
            [
                _ABSENT,                    # initial describe
                _ABSENT,                    # poll attempt 1
                CommandResult(0, "{}", ""),  # poll attempt 2 — appeared
            ]
        )
        sleeps: list[float] = []
        lines: list[str] = []
        ref = ensure_image_in_registry(
            runner, _env(), {"AWS_REGION": "us-east-1"},
            repo_path="/repo", tag="abc123", emit=lines.append,
            wait_budget_s=300, wait_poll_interval_s=30.0,
            sleeper=sleeps.append,
        )
        assert ref.endswith("yoke-core:abc123")
        # Wait mode never reaches docker/git — registry probes only.
        assert len(runner.calls) == 3
        for call in runner.calls:
            assert call["argv"][:3] == ["aws", "ecr", "describe-images"]
        assert sleeps == [30.0, 30.0]
        waiting = [
            line for line in lines if "waiting for prewarmed image" in line
        ]
        assert len(waiting) == 1
        assert "yoke-core:abc123 (attempt 1, 30s elapsed)" in waiting[0]
        assert any(
            "prewarmed image appeared" in line
            and "attempt 2, 60s elapsed" in line
            for line in lines
        )

    def test_budget_exhaustion_fails_with_teaching(self, monkeypatch):
        monkeypatch.setenv(IMAGE_WAIT_ENV_VAR, "1")
        # budget 90s / 30s interval -> exactly 3 polls after the initial
        # describe; every probe reports absent.
        runner = FakeRunner([_ABSENT] * 4)
        with pytest.raises(CoreDeployError) as exc:
            ensure_image_in_registry(
                runner, _env(env_name="stage"), {},
                repo_path="/repo", tag="abc123", emit=lambda _line: None,
                wait_budget_s=90, wait_poll_interval_s=30.0,
                sleeper=lambda _s: None,
            )
        message = str(exc.value)
        assert "wait exhausted" in message
        assert ".github/workflows/yoke-core-image.yml" in message
        assert "workflow_dispatch" in message
        assert "runs create-run yoke yoke-stage-release" in message
        assert "git -C <source-checkout> fetch origin <target-branch>" in message
        assert (
            "watch_deploy --product-src <source-checkout> -- <run-id>"
        ) in message
        assert "canonical image tag" in message
        # The runner-build path is unreachable: probes only, no docker.
        assert len(runner.calls) == 4
        for call in runner.calls:
            assert call["argv"][:3] == ["aws", "ecr", "describe-images"]

    def test_disabled_value_keeps_operator_build_path(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv(IMAGE_WAIT_ENV_VAR, "0")
        runner = FakeRunner(
            [
                _ABSENT,
                CommandResult(0, "", ""),  # git archive
                CommandResult(0, "", ""),  # tar extract
                CommandResult(1, "", "no buildx"),  # docker build attempted
            ]
        )
        with pytest.raises(CoreDeployError, match="docker build failed"):
            ensure_image_in_registry(
                runner, _env(), {},
                repo_path="/repo", tag="abc", emit=lambda _line: None,
                build_dir=tmp_path,
            )
        assert runner.calls[3]["argv"][:2] == ["docker", "build"]
