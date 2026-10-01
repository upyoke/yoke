"""Checkout image plans satisfy the image's release identity gate."""

import subprocess
from pathlib import Path
from packaging.version import Version
from setuptools_scm import get_version
from yoke_cli.local_core import checkout_build, docker_plan
from yoke_cli.local_core.launcher import LocalCoreLauncher
from runtime.api.cli.test_yoke_local_core_launcher import FakeRunner
from yoke_contracts.engine_version import UNRESOLVED_SCM_FALLBACK_VERSION

ROOT = Path(__file__).resolve().parents[3]


def test_checkout_plan_carries_real_git_commit_and_valid_version():
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    issues = []
    plan = docker_plan.build_plan(str(ROOT), "local/yoke:test", issues)[0]
    args = dict(part.split("=", 1) for part in plan if part.startswith("YOKE_"))
    assert not issues
    assert args["YOKE_BUILD_SHA"] == commit
    assert str(Version(args["YOKE_ENGINE_VERSION"])) == args["YOKE_ENGINE_VERSION"]
    assert args["YOKE_ENGINE_VERSION"] != UNRESOLVED_SCM_FALLBACK_VERSION
    assert args["YOKE_ENGINE_VERSION"] == get_version(root=str(ROOT))


def test_missing_git_identity_refuses_before_any_build(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    runner = FakeRunner()
    launcher = LocalCoreLauncher(
        runner=runner, machine_home=str(tmp_path / "home"), system="linux"
    )
    result = launcher.build(checkout_path=str(tmp_path))
    assert result["ok"] is False
    assert any(row["code"] == "checkout_build_identity" for row in result["issues"])
    assert not any(call[:2] == ("docker", "build") for call in runner.calls)


def test_git_failure_has_named_recovery(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 15)

    monkeypatch.setattr(checkout_build.subprocess, "run", fail)
    issues = []
    assert docker_plan.build_plan(str(ROOT), "local/yoke:test", issues) == []
    assert "repair or commit" in issues[0].message


def test_snapshot_version_advances_from_checkout_release_tag(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True
        )

    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "source").write_text("first")
    git("add", "source")
    git("commit", "-m", "initial")
    git("tag", "v2.4.6")
    (tmp_path / "source").write_text("second")
    git("commit", "-am", "changed")
    commit, version = checkout_build.identity(str(tmp_path))
    assert Version(version) > Version("2.4.6")
    assert version.startswith("2.4.7.dev1+")
    assert commit == git("rev-parse", "HEAD").stdout.decode().strip()


def test_missing_version_has_named_recovery(monkeypatch):
    def fail(**kwargs):
        raise LookupError("no SCM version")

    monkeypatch.setattr("setuptools_scm.get_version", fail)
    issues = []
    assert docker_plan.build_plan(str(ROOT), "local/yoke:test", issues) == []
    assert "fetch its release tags" in issues[0].message
