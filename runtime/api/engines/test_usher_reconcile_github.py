"""Tests for the usher reconcile-from-GitHub-truth helper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.engines import usher_reconcile_github as mod
from yoke_core.engines import usher_reconcile_github_verdict as verdict_mod


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def wired(monkeypatch):
    item_state = {"deploy_stage": "prod-deploy-failed"}
    emitted_events = []
    dispatched = []

    def fake_execution_context(run_id):
        assert run_id == "run-X"
        return {
            "run": {
                "project": "yoke",
                "flow": "yoke-hosted-production",
                "release_lineage": "deadbeef1234567890",
            },
            "stages": [
                {
                    "name": "prod-deploy",
                    "step_runner": "github-actions-workflow",
                    "workflow": "deploy.yml",
                }
            ],
        }

    def fake_github_actions(*args, project, sd=None, timeout=60):
        del sd, timeout
        assert project == "yoke"
        if args[0] == "find-run":
            return _proc(0, "987654321\n")
        if args[0] == "poll":
            return _proc(0, "success\n")
        return _proc(1, "")

    def fake_emit_run_event(name, outcome, context, *, member_items, project, sd=None):
        del sd
        emitted_events.append(
            {
                "name": name,
                "outcome": outcome,
                "context": context,
                "member_items": list(member_items),
                "project": project,
            }
        )

    def fake_call_dispatcher(*, function_id, target, payload, relay_env=None):
        del relay_env
        assert function_id == "items.scalar.update"
        dispatched.append(
            SimpleNamespace(function=function_id, target=target, payload=payload)
        )
        item_state["deploy_stage"] = payload["value"]
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(
        mod, "_item_deploy_stage", lambda _item_id: item_state["deploy_stage"]
    )
    monkeypatch.setattr(mod, "_resolve_run_for_item", lambda _item_id: "run-X")
    monkeypatch.setattr(mod.control_plane, "execution_context", fake_execution_context)
    monkeypatch.setattr(
        mod.control_plane,
        "project_field",
        lambda _project, _field: "anthropics/yoke",
    )
    monkeypatch.setattr(mod, "_github_actions", fake_github_actions)
    monkeypatch.setattr(verdict_mod, "_emit_run_event", fake_emit_run_event)
    monkeypatch.setattr(
        mod,
        "_display_item_ref",
        lambda item_id: f"YOK-{item_id}",
    )
    monkeypatch.setattr(verdict_mod, "call_dispatcher", fake_call_dispatcher)

    return SimpleNamespace(
        item_state=item_state,
        emitted_events=emitted_events,
        dispatched=dispatched,
    )


def test_alignment_emits_event_and_clears_deploy_stage(wired):
    result = mod.reconcile_item(42)

    assert result.outcome == "aligned"
    assert result.workflow_run_id == "987654321"
    assert "Resume usher with: /yoke usher YOK-42 --resume" in result.message

    assert len(wired.emitted_events) == 1
    event = wired.emitted_events[0]
    assert event["name"] == "DeploymentRunStageCompleted"
    assert event["outcome"] == "completed"
    ctx = event["context"]
    assert ctx["workflow_run"] == "987654321"
    assert ctx["stage"] == "prod-deploy"
    assert ctx["run_id"] == "run-X"
    assert ctx["reconciled"] is True
    assert ctx["reason"] == "usher-reconcile-github"
    assert event["member_items"] == ["42"]
    assert event["project"] == "yoke"

    assert len(wired.dispatched) == 1
    req = wired.dispatched[0]
    assert req.function == "items.scalar.update"
    assert req.target.kind == "item"
    assert req.target.item_id == 42
    assert req.payload == {"field": "deploy_stage", "value": "prod-deploy"}
    assert wired.item_state["deploy_stage"] == "prod-deploy"


@pytest.mark.parametrize(
    "gh_stdout", ["failed:failure", "failed:cancelled", "failed:timed_out"]
)
def test_github_failure_does_not_mutate(wired, monkeypatch, gh_stdout):
    def gh(*args, project, sd=None, timeout=60):
        del sd, timeout
        assert project == "yoke"
        if args[0] == "find-run":
            return _proc(0, "987654321\n")
        if args[0] == "poll":
            return _proc(1, gh_stdout + "\n")
        return _proc(1, "")

    monkeypatch.setattr(mod, "_github_actions", gh)

    result = mod.reconcile_item(42)

    assert result.outcome == "gh-failure"
    assert result.gh_conclusion in {"failure", "cancelled", "timed_out"}
    assert wired.emitted_events == []
    assert wired.dispatched == []
    assert wired.item_state["deploy_stage"] == "prod-deploy-failed"


@pytest.mark.parametrize("rc, status", [(2, "waiting"), (3, "in_progress")])
def test_github_running_does_not_mutate(wired, monkeypatch, rc, status):
    def gh(*args, project, sd=None, timeout=60):
        del sd, timeout
        assert project == "yoke"
        if args[0] == "find-run":
            return _proc(0, "987654321\n")
        if args[0] == "poll":
            return _proc(rc, status + "\n")
        return _proc(1, "")

    monkeypatch.setattr(mod, "_github_actions", gh)

    result = mod.reconcile_item(42)

    assert result.outcome == "gh-running"
    assert result.gh_status == status
    assert wired.emitted_events == []
    assert wired.dispatched == []
    assert wired.item_state["deploy_stage"] == "prod-deploy-failed"


def test_unresolved_run_id_errors_without_mutating(wired, monkeypatch):
    def gh(*args, project, sd=None, timeout=60):
        del sd, timeout
        assert project == "yoke"
        return _proc(1, "not_found\n") if args[0] == "find-run" else _proc(1, "")

    monkeypatch.setattr(mod, "_github_actions", gh)

    result = mod.reconcile_item(42)

    assert result.outcome == "error"
    assert "--workflow-run-id" in result.message
    assert wired.emitted_events == []
    assert wired.dispatched == []


def test_missing_deployment_run_errors(wired, monkeypatch):
    monkeypatch.setattr(mod, "_resolve_run_for_item", lambda _item_id: "")

    result = mod.reconcile_item(42)

    assert result.outcome == "error"
    assert "deployment_run_items" in result.message
    assert wired.dispatched == []


def test_missing_registered_repo_errors_before_actions(wired, monkeypatch):
    monkeypatch.setattr(mod.control_plane, "project_field", lambda _project, _field: "")

    result = mod.reconcile_item(42)

    assert result.outcome == "error"
    assert "no registered github_repo" in result.message
    assert wired.emitted_events == []
    assert wired.dispatched == []


def test_missing_release_lineage_errors_before_actions(wired, monkeypatch):
    def fake_execution_context(run_id):
        assert run_id == "run-X"
        return {
            "run": {"project": "yoke", "flow": "yoke-hosted-production"},
            "stages": [
                {
                    "name": "prod-deploy",
                    "step_runner": "github-actions-workflow",
                    "workflow": "deploy.yml",
                }
            ],
        }

    monkeypatch.setattr(mod.control_plane, "execution_context", fake_execution_context)

    result = mod.reconcile_item(42)

    assert result.outcome == "error"
    assert "no recorded release_lineage" in result.message
    assert "--workflow-run-id" in result.message
    assert wired.emitted_events == []
    assert wired.dispatched == []


def test_alignment_message_names_resume_command(wired):
    result = mod.reconcile_item(42)
    assert result.outcome == "aligned"
    assert result.message == (
        "Yoke records aligned with GitHub truth. "
        "Resume usher with: /yoke usher YOK-42 --resume"
    )


def test_operator_override_skips_find_run(wired, monkeypatch):
    poll_calls = []

    def gh(*args, project, sd=None, timeout=60):
        del sd, timeout
        assert project == "yoke"
        if args[0] == "find-run":
            raise AssertionError(
                "find-run must not be called when --workflow-run-id is supplied"
            )
        if args[0] == "poll":
            poll_calls.append(tuple(args))
            return _proc(0, "success\n")
        return _proc(1, "")

    monkeypatch.setattr(mod, "_github_actions", gh)

    result = mod.reconcile_item(42, workflow_run_id_override="operator-555")

    assert result.outcome == "aligned"
    assert result.workflow_run_id == "operator-555"
    assert poll_calls == [("poll", "anthropics/yoke", "operator-555")]


def test_source_never_names_phantom_column():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "workflow_run_id" in src  # references via --workflow-run-id are fine
    forbidden = (
        "deployment_runs.workflow_run_id",
        "FROM deployment_runs",
        'runs", "get", run_id, "workflow_run_id"',
    )
    for needle in forbidden:
        assert needle not in src, f"helper must not query phantom column ({needle!r})"


def test_no_action_when_deploy_stage_empty(wired, monkeypatch):
    monkeypatch.setattr(mod, "_item_deploy_stage", lambda _item_id: "")
    result = mod.reconcile_item(42)
    assert result.outcome == "no-action"
    assert wired.emitted_events == []
    assert wired.dispatched == []


def test_no_action_when_deploy_stage_not_failed_shape(wired, monkeypatch):
    monkeypatch.setattr(
        mod,
        "_item_deploy_stage",
        lambda _item_id: "complete",
    )
    result = mod.reconcile_item(42)
    assert result.outcome == "no-action"
    assert "<stage>-failed" in result.message
    assert wired.dispatched == []


def test_parse_item_argument_accepts_typed_internal_id():
    # PREFIX-N resolution (project sequence -> internal id) is covered by
    # the canonical parser tests; here only the DB-free shapes.
    assert mod._parse_item_argument(42) == 42


def test_parse_item_argument_rejects_empty():
    with pytest.raises(ValueError):
        mod._parse_item_argument("")
    with pytest.raises(ValueError):
        mod._parse_item_argument("   ")


def test_main_exits_with_usage_code_on_bad_arg(wired, capsys):
    rc = mod.main(["not-an-id"])
    assert rc == mod.EXIT_USAGE
    assert "expected PREFIX-N" in capsys.readouterr().err


def test_main_returns_zero_on_alignment(wired, monkeypatch, capsys):
    monkeypatch.setattr(mod, "_parse_item_argument", lambda _arg: 42)
    rc = mod.main(["42"])
    assert rc == mod.EXIT_OK
    assert "Resume usher with: /yoke usher YOK-42 --resume" in capsys.readouterr().out


def test_main_returns_running_code_when_gh_in_progress(wired, monkeypatch, capsys):
    monkeypatch.setattr(mod, "_parse_item_argument", lambda _arg: 42)

    def gh(*args, project, sd=None, timeout=60):
        del sd, timeout
        assert project == "yoke"
        if args[0] == "find-run":
            return _proc(0, "987654321\n")
        if args[0] == "poll":
            return _proc(3, "in_progress\n")
        return _proc(1, "")

    monkeypatch.setattr(mod, "_github_actions", gh)

    rc = mod.main(["42"])
    assert rc == mod.EXIT_RUNNING
    assert "still in_progress" in capsys.readouterr().out
