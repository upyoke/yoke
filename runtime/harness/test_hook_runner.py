"""Hook-runner behavior tests — timeout, subprocess carve-out, dry-run CLI, smoke.

Owns the typed-policy SIGALRM timeout, the subprocess carve-out
exit-zero / exit-nonzero / timeout paths, the dry-run CLI markers, the
real-chain ``sqlite3`` denial smoke test, and the file-line cap.

The parity surface (every ``(event, matcher)`` matches the universal
ordering source modulo each capability's ``apply_patch_chain_omissions``
filter, plus the structural backstop that every chained module is either
typed-evaluable or a subprocess carve-out) lives in
``test_hook_runner_parity.py``. Together the two files replace the
deleted ``runtime/harness/codex/test_codex_hooks_universal_order.py``
string-comparison snapshot.
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

from runtime.harness.claude.adapter import CAPABILITY as CLAUDE_CAPABILITY
from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner import telemetry as telemetry_module
from runtime.harness.hook_runner import subprocess_policy
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _silence_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop runner telemetry emissions so smoke tests don't touch the events table."""
    for name in (
        "emit_hook_execution_failed",
        "emit_hook_guardrail_evaluated",
        "emit_hook_dispatch_telemetry",
    ):
        monkeypatch.setattr(telemetry_module, name, lambda **k: None)


def _capture_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Capture ``HookExecutionFailed`` and ``HookGuardrailEvaluated`` payloads."""
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
    return failed, evaluated


def _patch_typed_modules(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, Any],
) -> None:
    """Substitute ``importlib.import_module`` for a closed set of dotted ids."""
    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        if name in mapping:
            return mapping[name]
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)


def _build_capability(
    monkeypatch: pytest.MonkeyPatch,
    chain: list[str],
    *,
    subprocess_modules: frozenset[str] = frozenset(),
) -> AdapterCapability:
    """Build a minimal capability + monkeypatch ``chain_for`` to return ``chain``."""
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: list(chain))
    return AdapterCapability(
        family="claude",
        payload_parser=lambda raw: {},
        decision_renderer=lambda decisions, event_name: ("", 0),
        subprocess_modules=subprocess_modules,
    )


def _fake_subprocess(stdout_text: str, returncode: int):
    def fake(argv, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=argv, returncode=returncode, stdout=stdout_text, stderr="",
        )

    return fake


# ---------------------------------------------------------------------------
# SIGALRM timeout watchdog -> HookExecutionFailed + chain continues
# ---------------------------------------------------------------------------


def test_timeout_emits_failed_event_and_chain_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed-policy timeout emits ``HookExecutionFailed{failure="timeout_<ms>ms"}``."""
    monkeypatch.setattr(runner_module, "_resolve_timeout_ms", lambda: 200)

    def slow(context: HookContext) -> HookDecision:  # noqa: ARG001
        time.sleep(0.7)  # 200ms timeout + 0.5 buffer per spec contract
        return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

    def downstream(context: HookContext) -> HookDecision:  # noqa: ARG001
        return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

    class _Slow:
        evaluate = staticmethod(slow)

    class _Down:
        evaluate = staticmethod(downstream)

    chain = ["mod.timeout_offender", "mod.downstream"]
    _patch_typed_modules(
        monkeypatch, {"mod.timeout_offender": _Slow, "mod.downstream": _Down},
    )
    capability = _build_capability(monkeypatch, chain)
    failed, evaluated = _capture_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    assert text == ""
    assert len(failed) == 1
    assert failed[0]["module"] == "mod.timeout_offender"
    assert failed[0]["failure"] == "timeout_200ms"
    # Downstream module's decision was rendered (chain continued past offender).
    assert len(evaluated) == 1
    assert evaluated[0]["module"] == "mod.downstream"

# ---------------------------------------------------------------------------
# Subprocess carve-out — exit 0 / exit 1 / timeout, all continue chain
# ---------------------------------------------------------------------------


def test_subprocess_exit_zero_emits_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess exit 0 emits ``HookGuardrailEvaluated``."""
    capability = _build_capability(
        monkeypatch, ["mod.subproc_ok"],
        subprocess_modules=frozenset({"mod.subproc_ok"}),
    )
    monkeypatch.setattr(
        subprocess_policy.subprocess, "run", _fake_subprocess("stdout-ok", 0),
    )
    failed, evaluated = _capture_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    assert "stdout-ok" in text
    assert failed == []
    assert len(evaluated) == 1
    assert evaluated[0]["module"] == "mod.subproc_ok"


def test_subprocess_exit_nonzero_emits_failed_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess exit 1 -> ``HookExecutionFailed`` + downstream still runs."""
    chain = ["mod.subproc_boom", "mod.typed_ok"]
    capability = _build_capability(
        monkeypatch, chain, subprocess_modules=frozenset({"mod.subproc_boom"}),
    )
    monkeypatch.setattr(
        subprocess_policy.subprocess, "run", _fake_subprocess("partial-stdout", 1),
    )

    def downstream(context: HookContext) -> HookDecision:  # noqa: ARG001
        return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

    class _Down:
        evaluate = staticmethod(downstream)

    _patch_typed_modules(monkeypatch, {"mod.typed_ok": _Down})
    failed, evaluated = _capture_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    assert "partial-stdout" in text  # captured stdout still relayed on failure
    assert len(failed) == 1
    assert failed[0]["module"] == "mod.subproc_boom"
    assert failed[0]["failure"] == "exit_1"
    assert len(evaluated) == 1
    assert evaluated[0]["module"] == "mod.typed_ok"


def test_subprocess_timeout_emits_failed_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subprocess timeout -> ``HookExecutionFailed{failure="timeout_<ms>ms"}``."""
    monkeypatch.setattr(runner_module, "_resolve_timeout_ms", lambda: 150)
    chain = ["mod.subproc_slow", "mod.typed_ok"]
    capability = _build_capability(
        monkeypatch, chain, subprocess_modules=frozenset({"mod.subproc_slow"}),
    )

    def fake_run(argv, **kwargs):  # noqa: ARG001
        # Mirror the real subprocess.run TimeoutExpired contract.
        raise subprocess.TimeoutExpired(cmd=argv, timeout=0.15)

    monkeypatch.setattr(subprocess_policy.subprocess, "run", fake_run)

    def downstream(context: HookContext) -> HookDecision:  # noqa: ARG001
        return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

    class _Down:
        evaluate = staticmethod(downstream)

    _patch_typed_modules(monkeypatch, {"mod.typed_ok": _Down})
    failed, evaluated = _capture_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    assert text == ""
    assert len(failed) == 1
    assert failed[0]["module"] == "mod.subproc_slow"
    assert failed[0]["failure"] == "timeout_150ms"
    assert len(evaluated) == 1
    assert evaluated[0]["module"] == "mod.typed_ok"


# ---------------------------------------------------------------------------
# Dry-run CLI prints [typed]/[subproc] markers and exits 0
# ---------------------------------------------------------------------------


def test_cli_dry_run_pretooluse_lists_typed_and_subproc_markers() -> None:
    """``PreToolUse --dry-run`` exits 0 and prints chain markers."""
    repo_root = str(Path(__file__).resolve().parents[2])
    # Prepend (not overwrite) so split-package paths on an inherited
    # PYTHONPATH survive into the child; needed when the yoke_* packages
    # run from source via PYTHONPATH rather than being editable-installed.
    _pp = os.pathsep.join(p for p in (repo_root, os.environ.get("PYTHONPATH", "")) if p)
    env = {**os.environ, "PYTHONPATH": _pp}
    completed = subprocess.run(
        [sys.executable, "-m", "runtime.harness.hook_runner", "PreToolUse", "--dry-run"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        cwd=repo_root,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    marker_lines = [
        line for line in completed.stdout.splitlines()
        if line.startswith("[typed]") or line.startswith("[subproc]")
    ]
    assert marker_lines, f"dry-run produced no marker lines:\n{completed.stdout}"
    # PreToolUse:Bash header proves the per-tool dry-run branch fired.
    assert "PreToolUse:Bash" in completed.stdout


# ---------------------------------------------------------------------------
# Real-chain smoke — sqlite3 invocation denies via lint_db_cmd
# ---------------------------------------------------------------------------


def test_real_chain_pretool_bash_sqlite3_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real PreToolUse Bash chain denies a raw ``sqlite3`` invocation."""
    _silence_telemetry(monkeypatch)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "sqlite3 data/yoke.db \"SELECT 1\""},
        "session_id": "sess-smoke",
        "cwd": "/tmp",
    }

    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: payload,
        decision_renderer=CLAUDE_CAPABILITY.decision_renderer,
        subprocess_modules=CLAUDE_CAPABILITY.subprocess_modules,
        apply_patch_chain_omissions=CLAUDE_CAPABILITY.apply_patch_chain_omissions,
        pretool_omissions=CLAUDE_CAPABILITY.pretool_omissions,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="{}",
    )

    # Claude renderer signals deny via exit code 2 with the narrative on stdout.
    assert exit_code == 2, f"expected deny exit 2, got {exit_code}; text={text!r}"
    assert "permissionDecision" in text or "deny" in text.lower()


# ---------------------------------------------------------------------------
# File-line cap (this file <= 350 lines)
# ---------------------------------------------------------------------------


def test_behavior_file_under_350_lines() -> None:
    """Behavior file at or below the 350-line hard cap."""
    here = Path(__file__).resolve()
    with here.open("rb") as fh:
        line_count = sum(1 for _ in fh)
    assert line_count <= 350, f"{here.name} is {line_count} lines"
