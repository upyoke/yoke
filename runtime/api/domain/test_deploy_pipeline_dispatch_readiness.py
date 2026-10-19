"""The CI gate waits while the dispatch's preparation runs; both must pass."""

from __future__ import annotations

import subprocess
import threading
from contextvars import ContextVar
from unittest import mock

from yoke_core.domain import deploy_pipeline_dispatch_readiness as readiness
from yoke_core.domain import deploy_pipeline_github_workflow

_OVERLAP_SECONDS = 5


def test_preparation_runs_while_the_ci_gate_waits() -> None:
    # Each side waits for the other to have started: run one after the other
    # and the first side times out instead of seeing its partner.
    gate_started = threading.Event()
    preparation_started = threading.Event()

    def ci_gate() -> tuple[bool, str]:
        gate_started.set()
        assert preparation_started.wait(_OVERLAP_SECONDS)
        return True, ""

    def before_dispatch() -> tuple[int, str]:
        preparation_started.set()
        assert gate_started.wait(_OVERLAP_SECONDS)
        assert threading.current_thread() is threading.main_thread()
        return 0, ""

    assert readiness.await_dispatch_readiness(ci_gate, before_dispatch) == (0, "")


def test_ci_gate_sees_the_dispatching_context() -> None:
    run = ContextVar("run", default="")
    token = run.set("run-1")
    seen: list[str] = []

    def ci_gate() -> tuple[bool, str]:
        seen.append(run.get())
        return True, ""

    try:
        assert readiness.await_dispatch_readiness(ci_gate, None) == (0, "")
    finally:
        run.reset(token)
    assert seen == ["run-1"]


def test_failed_preparation_refuses_though_ci_passed() -> None:
    result = readiness.await_dispatch_readiness(
        lambda: (True, "  CI gate: passed"),
        lambda: (1, "fleet rehearsal passed but its receipt does not cover x"),
    )

    assert result == (1, "fleet rehearsal passed but its receipt does not cover x")


def test_failed_ci_gate_refuses_after_the_preparation_finishes() -> None:
    prepared: list[str] = []

    def before_dispatch() -> tuple[int, str]:
        prepared.append("rehearsed")
        return 7, "rehearsal failed"

    result = readiness.await_dispatch_readiness(
        lambda: (False, "BLOCKED: CI failed"), before_dispatch
    )

    assert result == (1, "BLOCKED: CI failed")
    assert prepared == ["rehearsed"]


def test_skipped_ci_gate_still_runs_the_preparation(capsys) -> None:
    result = readiness.await_dispatch_readiness(None, lambda: (3, "refused"))

    assert result == (3, "refused")
    assert "CI gate: skipped" in capsys.readouterr().out


def _dispatch(before_dispatch, ci_gate, trigger):
    with (
        mock.patch.object(deploy_pipeline_github_workflow, "_check_ci_gate", ci_gate),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="abc1234\n"
            ),
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_find_existing_workflow_run",
            return_value=("", False, ""),
        ),
        mock.patch.object(deploy_pipeline_github_workflow, "_github_actions", trigger),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_poll_github_actions",
            return_value=(0, "completed: success"),
        ),
        mock.patch.object(deploy_pipeline_github_workflow, "_emit_run_event"),
    ):
        return deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
            {"workflow": "deploy.yml", "timeout_min": 30},
            name="prod-deploy",
            run_id="run-test",
            member_items=["42"],
            github_repo="owner/repo",
            project="externalwebapp",
            project_repo_path="",
            timeout_min=30,
            fresh=False,
            gate_branch="main",
            release_lineage="a" * 40,
            before_dispatch=before_dispatch,
            sd="/tmp/sd",
        )


def test_dispatch_refuses_without_a_covering_receipt() -> None:
    trigger = mock.Mock(
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="9\n")
    )

    rc, diagnostic = _dispatch(
        lambda: (1, "receipt does not cover 0002_rewrite_rows"),
        mock.Mock(return_value=(True, "")),
        trigger,
    )

    assert (rc, diagnostic) == (1, "receipt does not cover 0002_rewrite_rows")
    trigger.assert_not_called()


def test_dispatch_follows_the_ci_gate_once_the_receipt_is_ready() -> None:
    events: list[str] = []
    gate_started = threading.Event()

    def ci_gate(*_args, **_kwargs) -> tuple[bool, str]:
        gate_started.set()
        events.append("ci gate passed")
        return True, ""

    def before_dispatch() -> tuple[int, str]:
        assert gate_started.wait(_OVERLAP_SECONDS)
        events.append("receipt recorded")
        return 0, ""

    def trigger(*args, **_kwargs):
        events.append(f"github {args[0]}")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="9\n")

    assert _dispatch(before_dispatch, ci_gate, trigger)[0] == 0
    assert set(events[:2]) == {"ci gate passed", "receipt recorded"}
    assert events[2:] == ["github trigger-once"]
