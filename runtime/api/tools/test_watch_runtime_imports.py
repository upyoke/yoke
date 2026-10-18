"""A watcher can finish after its runtime source has been replaced."""

import builtins
import io
import sys

from yoke_core.domain.deploy_pipeline import EXIT_AWAITING_QA
from yoke_core.domain.deployment_run_completion_preconditions import (
    awaiting_qa_report_lines,
)
from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass, ThrottlePolicy


def test_terminal_wait_uses_modules_loaded_before_child_started(tmp_path, monkeypatch):
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
    report = "\n".join(awaiting_qa_report_lines("run-fixture", ["pending QA"]))
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
    assert result == EXIT_AWAITING_QA
    assert "outcome: waiting" in output.getvalue()
    assert "run-fixture" in output.getvalue()
    assert f"exit={EXIT_AWAITING_QA}" in output.getvalue()
    assert report in raw.read_text()
