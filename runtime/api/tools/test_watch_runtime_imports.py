"""A watcher can finish after its runtime source has been replaced."""

import builtins
import io
import sys

import pytest

from yoke_core.domain.deploy_pipeline import EXIT_AWAITING_QA
from yoke_core.domain.deployment_run_completion_preconditions import (
    awaiting_qa_report_lines,
)
from yoke_core.domain import watch_runner as _watch_runner
from yoke_core.domain.watch_throttle import Classification, LineClass, ThrottlePolicy


@pytest.mark.parametrize("has_hold_report", [True, False])
def test_terminal_outcome_uses_modules_loaded_before_child_started(
    tmp_path, monkeypatch, has_hold_report
):
    original_import = builtins.__import__
    original_launch = _watch_runner._launch_watched_child
    protected = {
        "yoke_core.domain.deploy_pipeline",
        "yoke_core.domain.deployment_run_completion_preconditions",
    }

    def unavailable(name, *args, **kwargs):
        if name in protected:
            raise ImportError("runtime source replaced while child ran")
        return original_import(name, *args, **kwargs)

    def launch(*args, **kwargs):
        child = original_launch(*args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", unavailable)
        return child

    monkeypatch.setattr(_watch_runner, "_launch_watched_child", launch)
    refusal = "Error: resume cannot skip required scoped QA: item-qa is unsettled"
    report = (
        "\n".join(awaiting_qa_report_lines("run-fixture", ["pending QA"]))
        if has_hold_report
        else refusal
    )
    output = io.StringIO()
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    result = _watch_runner.run_watcher(
        argv=[
            sys.executable,
            "-c",
            f"print({report!r}); raise SystemExit({EXIT_AWAITING_QA})",
        ],
        classifier=lambda _: Classification(LineClass.NOISE),
        raw_capture=raw,
        progress_capture=progress,
        kind="deploy",
        stdout_stream=output,
        policy=ThrottlePolicy(),
        outcome_only=True,
    )
    terminal = output.getvalue()
    if has_hold_report:
        assert result == 0
        assert "outcome: waiting" in terminal
        assert f"child_exit={EXIT_AWAITING_QA}" in terminal
        assert "run-fixture" in terminal
    else:
        assert result == EXIT_AWAITING_QA
        assert f"failure: {refusal}" in terminal
        assert "outcome: waiting" not in terminal
    assert terminal.splitlines()[-1] == f"# watch_deploy exit={result} raw={raw}"
    assert terminal == progress.read_text(encoding="utf-8")
    assert report in raw.read_text(encoding="utf-8")
