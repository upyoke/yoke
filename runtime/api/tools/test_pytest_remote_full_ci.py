"""Full CI answers a remote selection it already covers, or would answer as fast."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

from yoke_core.domain.qa_case_ci_lane import WorkflowRun
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.tools import ci_shards
from yoke_core.tools import pytest_remote_full_ci as full_ci
from yoke_core.tools import pytest_remote_selection as routing
from yoke_core.tools import pytest_remote_selection_report as report
from yoke_core.tools import pytest_remote_selection_run as engine

HEAD = "a" * 40


def _run(state: str, conclusion: str = "", head: str = HEAD) -> WorkflowRun:
    return WorkflowRun(
        run_id="900",
        status=state,
        conclusion=conclusion,
        html_url="https://github.com/acme/widgets/actions/runs/900",
        head_sha=head,
    )


@pytest.fixture()
def no_selection_run(monkeypatch) -> dict:
    """Fail the test if anything is pushed or dispatched; record what is followed."""
    seen: dict = {}
    monkeypatch.setattr(
        engine, "publish", lambda *a, **k: pytest.fail("must not push the lane")
    )
    monkeypatch.setattr(
        engine, "dispatch", lambda **k: pytest.fail("must not create a selection run")
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.github_actions_authority",
        contextlib.nullcontext,
    )
    monkeypatch.setattr(report, "record_wait", lambda **k: seen.update(wait=k))
    monkeypatch.setattr(report, "relay_failed_log", lambda **k: seen.update(relay=k) or "")
    monkeypatch.setattr(
        "yoke_core.domain.session_ci_wait_record.resolve_received_wait",
        lambda **k: "",
    )
    return seen


def _engine_run() -> int:
    return engine.run(
        root=Path("/tmp/lane"),
        project="widgets",
        workflow="sel.yml",
        repo="acme/widgets",
        branch="PRJ-7",
        head_sha=HEAD,
        base_sha="b" * 40,
        pytest_args=["-q"],
        dispatch_id="watch-pytest:x",
        continue_command="yoke watch pytest --impacted main --bounded",
    )


@pytest.mark.parametrize(
    ("covering", "conclusion", "exit_code"),
    [
        (_run("in_progress"), "success", 0),
        (_run("queued"), "failure", 1),
        (_run("completed", "success"), "success", 0),
    ],
)
def test_a_selection_is_skipped_when_full_ci_for_the_head_is_running_or_green(
    monkeypatch, capsys, no_selection_run, covering, conclusion, exit_code
) -> None:
    monkeypatch.setattr(
        engine,
        "full_ci_answer",
        lambda **k: full_ci.FullCiAnswer(run=covering, workflow="ci.yml"),
    )
    monkeypatch.setattr(
        report,
        "await_conclusion",
        lambda **k: no_selection_run.update(polled=k) or conclusion,
    )

    assert _engine_run() == exit_code

    out = capsys.readouterr().out
    assert "selection_skipped_full_ci_covers_head: ci.yml run 900" in out
    assert covering.html_url in out
    assert "no selection run was created" in out
    assert "ci_run_source=full_ci" in out
    assert "gh run download 900 -p 'pytest-output-*'" in out
    assert no_selection_run["polled"]["run_id"] == "900"
    assert no_selection_run["wait"]["run_id"] == "900"
    assert ("relay" in no_selection_run) is (conclusion == "failure")


def test_a_near_full_selection_takes_the_full_ci_path_and_creates_no_run(
    monkeypatch, capsys, no_selection_run, tmp_path
) -> None:
    root = tmp_path / "lane"
    root.mkdir()
    durations = {f"suite/test_{index}.py::test_case": 10.0 for index in range(100)}
    (root / ci_shards.DURATIONS_PATH).write_text(json.dumps(durations))
    monkeypatch.setattr(full_ci, "full_ci_workflow", lambda project: "ci.yml")
    monkeypatch.setattr(full_ci, "covering_run", lambda **k: None)
    monkeypatch.setattr(
        "yoke_core.tools.ci_selection_plan.selection_targets",
        lambda root, base_sha, passthrough: [f"suite/test_{i}.py" for i in range(90)],
    )
    monkeypatch.setattr(
        "yoke_core.tools.pytest_remote_full_scope.full_gate",
        lambda project: {"ci_workflow": "ci.yml"},
    )
    monkeypatch.setattr(
        "yoke_core.tools.pytest_remote_full_scope.gate_recovery",
        lambda root, project, gate: "yoke qa case run --requirement-id 12",
    )

    code = engine.run(
        root=root,
        project="widgets",
        workflow="sel.yml",
        repo="acme/widgets",
        branch="PRJ-7",
        head_sha=HEAD,
        base_sha="b" * 40,
        pytest_args=[],
        dispatch_id="watch-pytest:x",
    )

    assert code == routing.EXIT_REFUSED
    out = capsys.readouterr().out
    assert "estimate targets=90 profiled_tests=90 profiled_seconds=900" in out
    assert "Error: remote selection: selection_exceeds_full_ci_share" in out
    assert "Nothing was pushed or dispatched" in out
    assert "use `yoke qa case run --requirement-id 12`" in out


def test_an_unknowable_full_ci_state_refuses_rather_than_duplicating(
    monkeypatch, capsys, no_selection_run
) -> None:
    def unreadable(**_kwargs):
        raise full_ci.FullCiLookupFailed("HTTP 502")

    monkeypatch.setattr(engine, "full_ci_answer", unreadable)

    assert _engine_run() == routing.EXIT_UNREACHABLE
    out = capsys.readouterr().out
    assert "could not tell whether full CI already covers aaaaaaaaaaaa: HTTP 502" in out
    assert routing.LOCAL_FLAG in out


@pytest.mark.parametrize(
    ("found", "covers"),
    [
        (_run("in_progress"), True),
        (_run("queued"), True),
        (_run("completed", "success"), True),
        (_run("completed", "failure"), False),
        (_run("completed", "cancelled"), False),
        (_run("in_progress", head="c" * 40), False),
        (None, False),
    ],
)
def test_only_an_in_flight_or_green_run_on_the_exact_head_covers_it(
    monkeypatch, found, covers
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_covering_run.find_run_for_tree",
        lambda **kwargs: found,
    )
    run = full_ci.covering_run(
        project="widgets", repo="acme/widgets", workflow="ci.yml",
        head_sha=HEAD, timeout_seconds=5,
    )
    assert (run is not None) is covers


def test_a_failed_run_lookup_is_named(monkeypatch) -> None:
    def failing(**_kwargs):
        raise QaCaseExecutionError("could not query workflow runs")

    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_covering_run.find_run_for_tree", failing
    )
    with pytest.raises(full_ci.FullCiLookupFailed, match="could not query"):
        full_ci.covering_run(
            project="widgets", repo="acme/widgets", workflow="ci.yml",
            head_sha=HEAD, timeout_seconds=5,
        )


def test_a_covering_run_answers_before_the_selection_is_estimated(
    monkeypatch,
) -> None:
    monkeypatch.setattr(full_ci, "full_ci_workflow", lambda project: "ci.yml")
    monkeypatch.setattr(full_ci, "covering_run", lambda **k: _run("in_progress"))
    monkeypatch.setattr(
        full_ci, "threshold_refusal", lambda *a, **k: pytest.fail("not estimated")
    )

    answer = full_ci.full_ci_answer(
        root=Path("/tmp/lane"), project="widgets", repo="acme/widgets",
        head_sha=HEAD, base_sha="b" * 40, pytest_args=[], timeout_seconds=5,
    )

    assert answer.run is not None and answer.workflow == "ci.yml"
    assert answer.refusal == ""


def test_without_a_gate_the_refusal_names_the_attached_case_recipe(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.tools.pytest_remote_full_scope.full_gate", lambda project: None
    )
    command = full_ci.gate_command(Path("/tmp/lane"), "widgets")
    assert "yoke qa requirement list --item PREFIX-N" in command
