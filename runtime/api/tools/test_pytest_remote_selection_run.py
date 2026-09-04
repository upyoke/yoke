"""The remote selection engine: publish, dispatch or rejoin, and mirror the verdict."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_DISPATCHED_MARKER,
    WORKFLOW_DISPATCH_RECOVERED_MARKER,
)
from yoke_core.domain import deploy_pipeline_github_workflow_dispatch as dispatch_layer
from yoke_core.tools import pytest_remote_selection as routing
from yoke_core.tools import pytest_remote_selection_run as engine


def _run(monkeypatch, *, conclusion: str, publish_ok=True, dispatched=("42", engine.DISPATCHED)):
    seen: dict = {}
    monkeypatch.setattr(engine, "publish", lambda root, branch, head: publish_ok)
    monkeypatch.setattr(engine, "dispatch", lambda **kwargs: dispatched)
    monkeypatch.setattr(engine, "await_conclusion", lambda **kwargs: conclusion)
    monkeypatch.setattr(
        engine, "relay_failed_log", lambda **kwargs: seen.setdefault("failed_log", kwargs),
    )
    code = engine.run(
        root=Path("/tmp/lane"), project="yoke", workflow="sel.yml", repo="acme/widgets",
        branch="PRJ-7", head_sha="a" * 40, base_sha="b" * 40, pytest_args=["-q"],
        dispatch_id="watch-pytest:x",
    )
    return code, seen


@pytest.mark.parametrize(
    ("conclusion", "exit_code"),
    [
        ("success", 0),
        ("failure", 1),
        ("timed_out", routing.EXIT_TIMED_OUT),
        ("cancelled", routing.EXIT_CANCELLED),
        ("startup_failure", routing.EXIT_UNREACHABLE),
    ],
)
def test_exit_status_mirrors_the_conclusion(monkeypatch, capsys, conclusion, exit_code) -> None:
    code, seen = _run(monkeypatch, conclusion=conclusion)

    assert code == exit_code
    out = capsys.readouterr().out
    assert f"concluded {conclusion} exit={exit_code}" in out
    assert "ci_run_source=dispatched" in out
    if conclusion == "success":
        assert "failed_log" not in seen
    else:
        assert seen["failed_log"]["run_id"] == "42"
    if conclusion not in ("success", "failure"):
        assert "reached no verdict" in out


def test_publish_refusal_stops_before_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        engine, "dispatch", lambda **kwargs: pytest.fail("must not dispatch"),
    )
    code, _ = _run(monkeypatch, conclusion="success", publish_ok=False)

    assert code == routing.EXIT_UNREACHABLE


def test_dispatch_refusal_is_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(
        engine, "await_conclusion", lambda **kwargs: pytest.fail("must not poll"),
    )
    code, _ = _run(monkeypatch, conclusion="success", dispatched=None)

    assert code == routing.EXIT_UNREACHABLE


def test_rejoined_run_is_named_as_such(monkeypatch, capsys) -> None:
    code, _ = _run(monkeypatch, conclusion="success", dispatched=("7", engine.REJOINED))

    assert code == 0
    assert "rejoined run=7" in capsys.readouterr().out


def _completed(stdout: str, stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _dispatch(monkeypatch, result):
    seen: dict = {}

    def fake_trigger(args, *, github_actions, project, sd, timeout_sec):
        seen["args"] = list(args)
        seen["project"] = project
        return result

    monkeypatch.setattr(dispatch_layer, "trigger_with_recovery_retries", fake_trigger)
    outcome = engine.dispatch(
        project="yoke", repo="acme/widgets", workflow="sel.yml", branch="PRJ-7",
        head_sha="a" * 40, base_sha="b" * 40, pytest_args=["-q", "-k", "x y"],
        dispatch_id="watch-pytest:a:1", timeout_seconds=60,
    )
    return outcome, seen


def test_dispatch_carries_the_selection_inputs_and_correlation(monkeypatch) -> None:
    outcome, seen = _dispatch(
        monkeypatch, _completed("42\n", WORKFLOW_DISPATCH_DISPATCHED_MARKER),
    )

    assert outcome == ("42", engine.DISPATCHED)
    args = seen["args"]
    assert args[:3] == ["trigger", "acme/widgets", "sel.yml"]
    assert "--ref" in args and args[args.index("--ref") + 1] == "PRJ-7"
    assert f"base_sha={'b' * 40}" in args
    assert f"head_sha={'a' * 40}" in args
    assert "pytest_args=-q -k 'x y'" in args
    assert args[args.index("--request-id") + 1] == "watch-pytest:a:1"
    assert args[args.index("--correlation-input") + 1] == "yoke_dispatch_id"


def test_recovered_dispatch_is_a_rejoin(monkeypatch) -> None:
    outcome, _ = _dispatch(
        monkeypatch, _completed("42\n", WORKFLOW_DISPATCH_RECOVERED_MARKER),
    )
    assert outcome == ("42", engine.REJOINED)


def test_refused_dispatch_names_the_detail_and_the_opt_out(monkeypatch, capsys) -> None:
    outcome, _ = _dispatch(
        monkeypatch, _completed("", "workflow not found on ref", returncode=1),
    )

    assert outcome is None
    out = capsys.readouterr().out
    assert "workflow not found on ref" in out
    assert routing.LOCAL_FLAG in out


def test_await_conclusion_reads_the_poll(monkeypatch, capsys) -> None:
    from yoke_core.domain import deploy_pipeline_reporting

    monkeypatch.setattr(
        deploy_pipeline_reporting, "_poll_github_actions",
        lambda *a, **k: (1, "Run failed: failure\nsee log"),
    )
    conclusion = engine.await_conclusion(
        project="yoke", repo="acme/widgets", run_id="42", timeout_seconds=5,
    )

    assert conclusion == "failure"
    assert "see log" in capsys.readouterr().out


def test_main_splits_pytest_args_after_the_separator(monkeypatch) -> None:
    seen: dict = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(engine, "run", fake_run)
    code = engine.main([
        "--root", "/tmp/lane", "--project", "yoke", "--workflow", "sel.yml",
        "--repo", "acme/widgets", "--branch", "PRJ-7", "--head-sha", "a" * 40,
        "--dispatch-id", "d", "--", "-q", "-k", "x",
    ])

    assert code == 0
    assert seen["pytest_args"] == ["-q", "-k", "x"]
    assert seen["base_sha"] == ""


class TestFailureDetail:
    """A dispatch refusal must name what refused it, not the transport's hints."""

    def test_advisory_lines_do_not_become_the_reason(self) -> None:
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=(
                "yoke: this checkout and the server's build have diverged\n"
                "HTTP 404: Not Found\n"
            ),
        )

        assert engine.failure_detail(result) == "HTTP 404: Not Found"

    def test_stdout_answers_when_stderr_is_only_advisory(self) -> None:
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="workflow not found on the default branch\n",
            stderr="yoke: this checkout is 3 commits ahead\n",
        )

        assert engine.failure_detail(result) == (
            "workflow not found on the default branch"
        )

    def test_advisory_only_output_says_there_was_no_diagnostic(self) -> None:
        result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="yoke: a hint\n",
        )

        assert "no diagnostic" in engine.failure_detail(result)
