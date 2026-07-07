"""Subprocess-policy launch coverage for hook runner CLI modules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from runtime.harness.hook_runner import subprocess_policy as policy
from runtime.harness.hook_runner.types import HookContext


def test_observe_subprocess_gets_target_root_and_hook_args(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "runtime.harness.hook_runner.subprocess_policy.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "runtime.harness.hook_runner.service_client.target_authority_env",
        lambda root: {"YOKE_ROOT": root},
    )
    ctx = HookContext(
        event_name="PostToolUse",
        executor_family="codex",
        executor_surface="codex",
        payload={"tool_use_id": "tu-1"},
        session_id="sess-1",
        target_root=str(tmp_path),
    )

    failure, _stdout = policy.run_subprocess_policy(
        "yoke_core.domain.observe",
        context=ctx,
        stdin_data="{}",
        timeout_ms=1000,
    )

    assert failure is None
    assert captured["cwd"] == str(tmp_path)
    py_paths = captured["env"]["PYTHONPATH"].split(":")
    assert str(Path(policy.__file__).resolve().parents[3]) in py_paths
    assert str(tmp_path) in py_paths
    assert captured["env"]["YOKE_ROOT"] == str(tmp_path)
    assert captured["argv"][:3] == [
        sys.executable, "-m", "yoke_core.domain.observe",
    ]
    assert "--hook-event" in captured["argv"]
    assert "PostToolUse" in captured["argv"]
    assert "--session-id" in captured["argv"]
    assert "sess-1" in captured["argv"]


def test_non_observe_subprocess_keeps_plain_module_argv(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "runtime.harness.hook_runner.subprocess_policy.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "runtime.harness.hook_runner.service_client.target_authority_env",
        lambda root: {"YOKE_ROOT": root},
    )
    ctx = HookContext(
        event_name="PostToolUse",
        executor_family="codex",
        executor_surface="codex",
        payload={},
        target_root=str(tmp_path),
    )

    failure, _stdout = policy.run_subprocess_policy(
        "yoke_core.domain.db_error_hook",
        context=ctx,
        stdin_data="{}",
        timeout_ms=1000,
    )

    assert failure is None
    assert captured["cwd"] == str(tmp_path)
    assert captured["argv"] == [
        sys.executable, "-m", "yoke_core.domain.db_error_hook",
    ]
