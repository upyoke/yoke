"""Deadline exhaustion names every skipped guard."""

from __future__ import annotations

from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.skipped_guards import record_skipped_guards


def test_skipped_guards_are_named_on_controls_and_stderr(capsys) -> None:
    controls = RunControls()
    record_skipped_guards(
        ["yoke_core.domain.lint_destructive_git", "yoke_core.domain.observe_pre"],
        controls,
    )

    assert controls.degraded == [
        "deadline_skipped:2:yoke_core.domain.lint_destructive_git,"
        "yoke_core.domain.observe_pre"
    ]
    err = capsys.readouterr().err
    assert "skipped 2 guards" in err
    assert "lint_destructive_git" in err
