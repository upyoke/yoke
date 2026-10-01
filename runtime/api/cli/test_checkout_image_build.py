"""Checkout image plans satisfy the image's release identity gate."""

import subprocess
from pathlib import Path
from packaging.version import Version
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
    assert commit[:12] in args["YOKE_ENGINE_VERSION"]


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
