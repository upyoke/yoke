"""Tests for ``yoke_core.hooks.runner``.

Covers the typed SIGALRM timeout (``HookExecutionFailed`` + chain
continues), subprocess success (stdout appended +
``HookGuardrailEvaluated``), subprocess exit 1 (``HookExecutionFailed``
+ downstream still runs), file-line caps, the ordering invariant, and
the dry-run unit. The CLI ``--help`` / ``--dry-run`` cases shell out
through a real subprocess.
"""

from __future__ import annotations

from runtime.harness.hook_runner_runner_test_support import (
    _SUBPROC_RUN as _SUBPROC_RUN,
    _capability as _capability,
    _patch_typed_modules as _patch_typed_modules,
    _silence_telemetry as _silence_telemetry,
)


import importlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from yoke_core.hooks import runner as runner_module
from yoke_core.hooks import telemetry as telemetry_module
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


# ---------------------------------------------------------------------------
# CLI shell-out
# ---------------------------------------------------------------------------


_REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _run_cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    _pp = os.pathsep.join(
        p for p in (_REPO_ROOT, os.environ.get("PYTHONPATH", "")) if p
    )
    env = {**os.environ, "PYTHONPATH": _pp}
    return subprocess.run(
        [sys.executable, "-m", "yoke_core.hooks", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        cwd=_REPO_ROOT,
        env=env,
    )


def test_cli_help_exits_zero_and_lists_flags() -> None:
    """``--help`` exits 0 and surfaces ``event_name`` + ``--dry-run``."""
    completed = _run_cli("--help")
    assert completed.returncode == 0, completed.stderr
    assert "event_name" in completed.stdout
    assert "--dry-run" in completed.stdout


def test_cli_dry_run_pretooluse_lists_chain_and_exits_zero() -> None:
    """``PreToolUse --dry-run`` prints the chain and exits 0."""
    completed = _run_cli("PreToolUse", "--dry-run")
    assert completed.returncode == 0, completed.stderr
    assert "PreToolUse:Bash" in completed.stdout
    chain_lines = [
        line
        for line in completed.stdout.splitlines()
        if line.startswith("[typed]") or line.startswith("[subproc]")
    ]
    assert chain_lines, "dry-run produced no policy lines"


# ---------------------------------------------------------------------------
# Synthetic typed-policy modules (used by multiple tests below)
# ---------------------------------------------------------------------------


def _slow_evaluate(context: HookContext) -> HookDecision:  # noqa: ARG001
    """Sleeps past the configured timeout to provoke the SIGALRM watchdog."""
    timeout_ms = runner_module._resolve_timeout_ms()
    time.sleep(timeout_ms / 1000.0 + 0.5)
    return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)


def _allow_evaluate(context: HookContext) -> HookDecision:  # noqa: ARG001
    return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)


def test_typed_policy_timeout_emits_failed_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SIGALRM timeout -> HookExecutionFailed + chain continues."""
    monkeypatch.setattr(runner_module, "_resolve_timeout_ms", lambda: 200)
    chain = ["mod.slow", "mod.ok"]

    class _Slow:
        evaluate = staticmethod(_slow_evaluate)

    class _Ok:
        evaluate = staticmethod(_allow_evaluate)

    _patch_typed_modules(monkeypatch, {"mod.slow": _Slow, "mod.ok": _Ok})
    capability = _capability(monkeypatch, chain)

    failed: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_execution_failed",
        lambda **k: failed.append(k),
    )
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_guardrail_evaluated",
        lambda **k: evaluated.append(k),
    )
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_dispatch_telemetry",
        lambda **k: None,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse",
        capability=capability,
        stdin_data="",
    )

    assert exit_code == 0
    assert text == ""
    assert len(failed) == 1
    assert failed[0]["module"] == "mod.slow"
    assert failed[0]["failure"] == "timeout_200ms"
    # Downstream still ran.
    assert len(evaluated) == 1
    assert evaluated[0]["module"] == "mod.ok"


# ---------------------------------------------------------------------------
# Subprocess success / failure
# ---------------------------------------------------------------------------


def _make_fake_subprocess(stdout_text: str, returncode: int):
    def fake(argv, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=argv,
            returncode=returncode,
            stdout=stdout_text,
            stderr="",
        )

    return fake


def test_subprocess_success_appends_stdout_and_emits_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess exit 0 -> stdout appended + HookGuardrailEvaluated."""
    capability = _capability(
        monkeypatch,
        ["mod.subproc"],
        subprocess_modules=frozenset({"mod.subproc"}),
    )
    monkeypatch.setattr(
        _SUBPROC_RUN,
        _make_fake_subprocess("subproc-narrative", 0),
    )

    evaluated: list[dict[str, Any]] = []
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_guardrail_evaluated",
        lambda **k: evaluated.append(k),
    )
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_execution_failed",
        lambda **k: None,
    )
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_dispatch_telemetry",
        lambda **k: None,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse",
        capability=capability,
        stdin_data="",
    )

    assert exit_code == 0
    assert "subproc-narrative" in text
    assert len(evaluated) == 1
    assert evaluated[0]["module"] == "mod.subproc"


def test_subprocess_exit_one_emits_failed_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess exit 1 -> HookExecutionFailed + downstream still runs."""
    capability = _capability(
        monkeypatch,
        ["mod.boom", "mod.ok"],
        subprocess_modules=frozenset({"mod.boom"}),
    )
    monkeypatch.setattr(
        _SUBPROC_RUN,
        _make_fake_subprocess("boom-narrative", 1),
    )

    class _Ok:
        evaluate = staticmethod(_allow_evaluate)

    _patch_typed_modules(monkeypatch, {"mod.ok": _Ok})

    failed: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_execution_failed",
        lambda **k: failed.append(k),
    )
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_guardrail_evaluated",
        lambda **k: evaluated.append(k),
    )
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_dispatch_telemetry",
        lambda **k: None,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse",
        capability=capability,
        stdin_data="",
    )

    assert exit_code == 0
    assert "boom-narrative" in text  # stdout still appended on failure
    assert len(failed) == 1
    assert failed[0]["module"] == "mod.boom"
    assert failed[0]["failure"] == "exit_1"
    assert len(evaluated) == 1
    assert evaluated[0]["module"] == "mod.ok"


# ---------------------------------------------------------------------------
# Ordering preservation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# File-line caps + dry-run unit
# ---------------------------------------------------------------------------


def test_runner_and_main_files_under_350_lines() -> None:
    """runner.py and __main__.py each <= 350 lines."""
    pkg = Path(runner_module.__file__).resolve().parent
    for filename in ("runner.py", "__main__.py"):
        with (pkg / filename).open("rb") as fh:
            count = sum(1 for _ in fh)
        assert count <= 350, f"{filename} is {count} lines"


def test_dry_run_returns_chain_lines_no_policy_invoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_event(dry_run=True) returns formatted chain and invokes nothing."""
    capability = _capability(
        monkeypatch,
        ["mod.alpha", "mod.beta"],
        subprocess_modules=frozenset({"mod.beta"}),
    )

    def boom_import(name: str) -> Any:
        raise AssertionError(f"dry-run should not import {name}")

    def boom_subprocess(*a, **k):
        raise AssertionError("dry-run should not invoke subprocess")

    monkeypatch.setattr(importlib, "import_module", boom_import)
    monkeypatch.setattr(_SUBPROC_RUN, boom_subprocess)

    # SessionEnd is NOT tool-shaped, so the dry-run takes the single-chain branch.
    text, exit_code = runner_module.run_event(
        "SessionEnd",
        capability=capability,
        stdin_data="",
        dry_run=True,
    )
    assert exit_code == 0
    assert "[typed] mod.alpha" in text
    assert "[subproc] mod.beta" in text
