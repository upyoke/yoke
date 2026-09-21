"""Self-deploy pin lives in the pipeline process, not the product CLI."""

from __future__ import annotations

import io
from contextlib import nullcontext, redirect_stdout

import pytest

from yoke_core.domain import deploy_pipeline_liveness_cli as liveness_cli
from yoke_core.domain.deploy_pipeline_pinned_source import (
    DeployPinnedSourceError,
    PINNED_RELEASE_ENV,
    PINNED_REEXEC_ENV,
    PINNED_SOURCE_ROOT_ENV,
)

_PINNED_ENV = {
    PINNED_RELEASE_ENV: "abc",
    PINNED_SOURCE_ROOT_ENV: "/pin",
    "PATH": "/bin",
}


def _quiet_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Pump:
        def running(self):
            return nullcontext()

    monkeypatch.setattr(liveness_cli, "SessionLivenessPump", _Pump)
    monkeypatch.setattr(liveness_cli.deploy_pipeline, "main", lambda _argv: 0)


def _must_not(message: str):
    def _raise(*_a, **_k):
        raise AssertionError(message)

    return _raise


def test_liveness_cli_reexecs_into_the_pinned_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.tools.deploy_pipeline_pinned_driver.child_environment",
        lambda _run_id: dict(_PINNED_ENV),
    )
    monkeypatch.setattr(
        "yoke_core.tools.deploy_pipeline_pinned_driver.frozen_driver_notice",
        lambda env: f"Self-deploy driver frozen at {env[PINNED_RELEASE_ENV]}",
    )
    calls: list[tuple] = []

    def fake_execve(exe, argv, env):
        calls.append((exe, list(argv), dict(env)))
        raise SystemExit(0)

    monkeypatch.setattr(liveness_cli.os, "execve", fake_execve)
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as exited:
            liveness_cli.main(["run-1"])
    assert exited.value.code == 0
    exe, argv, env = calls[0]
    assert exe == liveness_cli.sys.executable
    assert argv[:3] == [
        liveness_cli.sys.executable,
        "-m",
        liveness_cli._ENGINE,
    ]
    assert argv[3:] == ["run-1"]
    assert env[PINNED_RELEASE_ENV] == "abc"
    assert env[PINNED_REEXEC_ENV] == "1"
    assert "frozen at" in out.getvalue()


def test_liveness_cli_does_not_reexec_on_the_relayed_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.tools.deploy_pipeline_pinned_driver.child_environment",
        lambda _run_id: None,
    )
    monkeypatch.setattr(
        liveness_cli.os,
        "execve",
        _must_not("relayed path must not reexec"),
    )
    _quiet_pipeline(monkeypatch)
    assert liveness_cli.main(["run-1"]) == 0


def test_liveness_cli_skips_reexec_when_already_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PINNED_REEXEC_ENV, "1")
    monkeypatch.setattr(
        "yoke_core.tools.deploy_pipeline_pinned_driver.child_environment",
        _must_not("already-pinned process must not pin again"),
    )
    monkeypatch.setattr(
        liveness_cli.os,
        "execve",
        _must_not("already-pinned process must not reexec"),
    )
    _quiet_pipeline(monkeypatch)
    assert liveness_cli.main(["run-1"]) == 0


def test_liveness_cli_skips_reexec_when_watch_already_bound_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PINNED_RELEASE_ENV, "abc")
    monkeypatch.setenv(PINNED_SOURCE_ROOT_ENV, "/pin")
    monkeypatch.setattr(
        "yoke_core.tools.deploy_pipeline_pinned_driver.child_environment",
        _must_not("watch-bound child must not pin again"),
    )
    monkeypatch.setattr(
        liveness_cli.os,
        "execve",
        _must_not("watch-bound child must not reexec"),
    )
    _quiet_pipeline(monkeypatch)
    assert liveness_cli.main(["run-1"]) == 0


def test_liveness_cli_prints_freeze_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(_run_id: str) -> None:
        raise DeployPinnedSourceError("cannot freeze")

    monkeypatch.setattr(
        "yoke_core.tools.deploy_pipeline_pinned_driver.child_environment",
        _raise,
    )
    assert liveness_cli.main(["run-1"]) == 2
    assert "cannot freeze" in capsys.readouterr().err
