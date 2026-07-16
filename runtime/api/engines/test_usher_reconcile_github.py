"""Tests for the usher reconcile-from-GitHub-truth helper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.engines import usher_reconcile_github as mod


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def wired(monkeypatch):
    item_state = {"deploy_stage": "prod-deploy-failed"}
    emitted_events = []
    dispatched = []

    def fake_yoke_db(*args, sd=None):
        del sd
        if args[:2] == ("items", "get") and len(args) > 3 and args[3] == "deploy_stage":
            return item_state["deploy_stage"]
        if args[:2] == ("runs", "get"):
            return "run-X|yoke|yoke-hosted-production|production|abc|failed|hosted-release|2026-05-19T00:00:00Z"
        return ""

    def fake_flow_db(*args, sd=None):
        del sd
        if args[0] == "stages":
            return '[{"name":"prod-deploy","executor":"github-actions-workflow","workflow":"deploy.yml"}]'
        return ""

    def fake_find_by_item(item_id, status=None, db_path=None):
        del status, db_path
        return "run-X|failed|prod-deploy|2026-05-19T00:00:00Z" if item_id == 42 else ""

    def fake_run_cmd(cmd, timeout=60):
        del timeout
        return _proc(0, "deadbeef1234567890\n")

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
        emitted_events.append({
            "name": name, "outcome": outcome, "context": context,
            "member_items": list(member_items), "project": project,
        })

    def fake_dispatch(request, *, ambient_session_id=None):
        del ambient_session_id
        dispatched.append(request)
        item_state["deploy_stage"] = request.payload["value"]
        return SimpleNamespace(success=True)

    monkeypatch.setattr(mod, "_yoke_db", fake_yoke_db)
    monkeypatch.setattr(
        mod,
        "resolve_project_github_auth",
        lambda project: SimpleNamespace(project=project, repo="anthropics/yoke"),
    )
    monkeypatch.setattr(mod, "_flow_db", fake_flow_db)
    monkeypatch.setattr(mod, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(mod, "_github_actions", fake_github_actions)
    monkeypatch.setattr(mod, "_emit_run_event", fake_emit_run_event)
    monkeypatch.setattr(
        "yoke_core.domain.deployment_runs_crud_query.cmd_find_by_item",
        fake_find_by_item,
    )
    monkeypatch.setattr(
        "yoke_core.domain.yoke_function_dispatch.dispatch", fake_dispatch,
    )

    return SimpleNamespace(
        item_state=item_state, emitted_events=emitted_events,
        dispatched=dispatched,
    )

def test_ac2_alignment_emits_event_and_clears_deploy_stage(wired):
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

@pytest.mark.parametrize("gh_stdout", ["failed:failure", "failed:cancelled", "failed:timed_out"])
def test_ac3_gh_failure_does_not_mutate(wired, monkeypatch, gh_stdout):
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
def test_ac4_gh_running_does_not_mutate(wired, monkeypatch, rc, status):
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

def test_ac5_unresolved_run_id_errors_without_mutating(wired, monkeypatch):
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


def test_ac5_missing_deployment_run_errors(wired, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deployment_runs_crud_query.cmd_find_by_item",
        lambda item_id, status=None, db_path=None: "",
    )

    result = mod.reconcile_item(42)

    assert result.outcome == "error"
    assert "deployment_run_items" in result.message
    assert wired.dispatched == []


def test_missing_verified_binding_errors_before_actions(wired, monkeypatch):
    from yoke_core.domain.project_github_auth import MissingRepoBinding

    monkeypatch.setattr(
        mod,
        "resolve_project_github_auth",
        lambda project: (_ for _ in ()).throw(
            MissingRepoBinding(project, "not bound")
        ),
    )

    result = mod.reconcile_item(42)

    assert result.outcome == "error"
    assert "GitHub App access" in result.message
    assert wired.emitted_events == []
    assert wired.dispatched == []

def test_ac6_alignment_message_names_resume_command(wired):
    result = mod.reconcile_item(42)
    assert result.outcome == "aligned"
    assert result.message == (
        "Yoke records aligned with GitHub truth. "
        "Resume usher with: /yoke usher YOK-42 --resume"
    )

def test_ac11_operator_override_skips_find_run(wired, monkeypatch):
    poll_calls = []

    def gh(*args, project, sd=None, timeout=60):
        del sd, timeout
        assert project == "yoke"
        if args[0] == "find-run":
            raise AssertionError("find-run must not be called when --workflow-run-id is supplied")
        if args[0] == "poll":
            poll_calls.append(tuple(args))
            return _proc(0, "success\n")
        return _proc(1, "")
    monkeypatch.setattr(mod, "_github_actions", gh)

    result = mod.reconcile_item(42, workflow_run_id_override="operator-555")

    assert result.outcome == "aligned"
    assert result.workflow_run_id == "operator-555"
    assert poll_calls == [("poll", "anthropics/yoke", "operator-555")]

def test_ac12_source_never_names_phantom_column():
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
    monkeypatch.setattr(mod, "_yoke_db", lambda *args, sd=None: "")
    result = mod.reconcile_item(42)
    assert result.outcome == "no-action"
    assert wired.emitted_events == []
    assert wired.dispatched == []


def test_no_action_when_deploy_stage_not_failed_shape(wired, monkeypatch):
    monkeypatch.setattr(
        mod, "_yoke_db",
        lambda *args, sd=None: "complete" if args[:2] == ("items", "get") else "",
    )
    result = mod.reconcile_item(42)
    assert result.outcome == "no-action"
    assert "<stage>-failed" in result.message
    assert wired.dispatched == []

def test_parse_item_id_accepts_yok_prefix_and_bare_int():
    assert mod._parse_item_id("YOK-42") == 42
    assert mod._parse_item_id("yok-042") == 42
    assert mod._parse_item_id("42") == 42
    assert mod._parse_item_id("0042") == 42


def test_parse_item_id_rejects_empty():
    with pytest.raises(ValueError):
        mod._parse_item_id("")
    with pytest.raises(ValueError):
        mod._parse_item_id("   ")


def test_main_exits_with_usage_code_on_bad_arg(wired, capsys):
    rc = mod.main(["not-an-id"])
    assert rc == mod.EXIT_USAGE
    assert "cannot parse item id" in capsys.readouterr().err


def test_main_returns_zero_on_alignment(wired, capsys):
    rc = mod.main(["YOK-42"])
    assert rc == mod.EXIT_OK
    assert "Resume usher with: /yoke usher YOK-42 --resume" in capsys.readouterr().out


def test_main_returns_running_code_when_gh_in_progress(wired, monkeypatch, capsys):
    def gh(*args, project, sd=None, timeout=60):
        del sd, timeout
        assert project == "yoke"
        if args[0] == "find-run":
            return _proc(0, "987654321\n")
        if args[0] == "poll":
            return _proc(3, "in_progress\n")
        return _proc(1, "")
    monkeypatch.setattr(mod, "_github_actions", gh)

    rc = mod.main(["YOK-42"])
    assert rc == mod.EXIT_RUNNING
    assert "still in_progress" in capsys.readouterr().out
