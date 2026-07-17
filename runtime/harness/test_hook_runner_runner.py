"""Tests for ``runtime.harness.hook_runner.runner``.

Covers the typed SIGALRM timeout (``HookExecutionFailed`` + chain
continues), subprocess success (stdout appended +
``HookGuardrailEvaluated``), subprocess exit 1 (``HookExecutionFailed``
+ downstream still runs), file-line caps, the ordering invariant, and
the dry-run unit. The CLI ``--help`` / ``--dry-run`` cases shell out
through a real subprocess.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner import telemetry as telemetry_module
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_claude_decision
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome

def _capability(
    monkeypatch: pytest.MonkeyPatch,
    chain: list[str],
    *,
    subprocess_modules: frozenset[str] = frozenset(),
) -> AdapterCapability:
    """Build a capability + monkeypatch chain_registry to return ``chain``."""
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: list(chain))
    return AdapterCapability(
        family="claude",
        payload_parser=lambda raw: {},
        decision_renderer=render_claude_decision,
        subprocess_modules=subprocess_modules,
    )

def _silence_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "emit_hook_execution_failed",
        "emit_hook_guardrail_evaluated",
        "emit_hook_dispatch_telemetry",
    ):
        monkeypatch.setattr(telemetry_module, name, lambda **k: None)


# ---------------------------------------------------------------------------
# CLI shell-out
# ---------------------------------------------------------------------------


_REPO_ROOT = str(Path(__file__).resolve().parents[2])
_SUBPROC_RUN = "runtime.harness.hook_runner.subprocess_policy.subprocess.run"

def _run_cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    _pp = os.pathsep.join(p for p in (_REPO_ROOT, os.environ.get("PYTHONPATH", "")) if p)
    env = {**os.environ, "PYTHONPATH": _pp}
    return subprocess.run(
        [sys.executable, "-m", "runtime.harness.hook_runner", *args],
        input=stdin, capture_output=True, text=True, timeout=15, check=False,
        cwd=_REPO_ROOT, env=env,
    )

def test_cli_help_exits_zero_and_lists_flags() -> None:
    """AC-5: ``--help`` exits 0 and surfaces ``event_name`` + ``--dry-run``."""
    completed = _run_cli("--help")
    assert completed.returncode == 0, completed.stderr
    assert "event_name" in completed.stdout
    assert "--dry-run" in completed.stdout

def test_cli_dry_run_pretooluse_lists_chain_and_exits_zero() -> None:
    """AC-6: ``PreToolUse --dry-run`` prints the chain and exits 0."""
    completed = _run_cli("PreToolUse", "--dry-run")
    assert completed.returncode == 0, completed.stderr
    assert "PreToolUse:Bash" in completed.stdout
    chain_lines = [
        line for line in completed.stdout.splitlines()
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

def _patch_typed_modules(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, Any],
) -> None:
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        if name in mapping:
            return mapping[name]
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)

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
        telemetry_module, "emit_hook_dispatch_telemetry", lambda **k: None,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
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
            args=argv, returncode=returncode, stdout=stdout_text, stderr="",
        )

    return fake

def test_subprocess_success_appends_stdout_and_emits_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess exit 0 -> stdout appended + HookGuardrailEvaluated."""
    capability = _capability(
        monkeypatch, ["mod.subproc"], subprocess_modules=frozenset({"mod.subproc"}),
    )
    monkeypatch.setattr(
        _SUBPROC_RUN, _make_fake_subprocess("subproc-narrative", 0),
    )

    evaluated: list[dict[str, Any]] = []
    monkeypatch.setattr(
        telemetry_module,
        "emit_hook_guardrail_evaluated",
        lambda **k: evaluated.append(k),
    )
    monkeypatch.setattr(
        telemetry_module, "emit_hook_execution_failed", lambda **k: None,
    )
    monkeypatch.setattr(
        telemetry_module, "emit_hook_dispatch_telemetry", lambda **k: None,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
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
        monkeypatch, ["mod.boom", "mod.ok"], subprocess_modules=frozenset({"mod.boom"}),
    )
    monkeypatch.setattr(
        _SUBPROC_RUN, _make_fake_subprocess("boom-narrative", 1),
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
        telemetry_module, "emit_hook_dispatch_telemetry", lambda **k: None,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
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

def test_ordering_preserved_with_mixed_typed_and_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = ["mod.first", "mod.middle", "mod.third"]
    capability = _capability(
        monkeypatch, chain, subprocess_modules=frozenset({"mod.middle"}),
    )
    invocations: list[str] = []

    def make_typed(mid: str):
        def evaluate(ctx: HookContext) -> HookDecision:  # noqa: ARG001
            invocations.append(mid)
            return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

        return evaluate

    class _First:
        evaluate = staticmethod(make_typed("mod.first"))

    class _Third:
        evaluate = staticmethod(make_typed("mod.third"))

    _patch_typed_modules(monkeypatch, {"mod.first": _First, "mod.third": _Third})

    def fake_run(argv, **kwargs):  # noqa: ARG001
        invocations.append("mod.middle")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_SUBPROC_RUN, fake_run)
    _silence_telemetry(monkeypatch)

    runner_module.run_event("PreToolUse", capability=capability, stdin_data="")
    assert invocations == ["mod.first", "mod.middle", "mod.third"]


def test_typed_policy_stdout_audit_field_is_appended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle policies can return hook stdout without printing directly."""
    capability = _capability(monkeypatch, ["mod.lifecycle"])

    class _Lifecycle:
        @staticmethod
        def evaluate(context: HookContext) -> HookDecision:  # noqa: ARG001
            return HookDecision(
                outcome=Outcome.AUDIT_ONLY,
                audit_fields={"stdout": "orientation\n"},
            )

    _patch_typed_modules(monkeypatch, {"mod.lifecycle": _Lifecycle})
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "SessionStart", capability=capability, stdin_data="",
    )
    assert exit_code == 0
    assert text == "orientation\n"


# ---------------------------------------------------------------------------
# File-line caps + dry-run unit
# ---------------------------------------------------------------------------

def test_runner_and_main_files_under_350_lines() -> None:
    """runner.py and __main__.py each <= 350 lines."""
    pkg = Path(__file__).resolve().parent / "hook_runner"
    for filename in ("runner.py", "__main__.py"):
        with (pkg / filename).open("rb") as fh:
            count = sum(1 for _ in fh)
        assert count <= 350, f"{filename} is {count} lines"

def test_dry_run_returns_chain_lines_no_policy_invoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_event(dry_run=True) returns formatted chain and invokes nothing."""
    capability = _capability(
        monkeypatch, ["mod.alpha", "mod.beta"],
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
        "SessionEnd", capability=capability, stdin_data="", dry_run=True,
    )
    assert exit_code == 0
    assert "[typed] mod.alpha" in text
    assert "[subproc] mod.beta" in text
