"""Lane resolution and workflow plumbing for the CI-run QA runner."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import qa_case_ci_lane as lane
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def _repo(tmp_path: Path, *, remote: str) -> Path:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(checkout)], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "remote", "add", "origin", remote],
        check=True,
    )
    (checkout / "file.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "-c", "user.email=t@example.com",
         "-c", "user.name=T", "commit", "-q", "-m", "seed"],
        check=True,
    )
    return checkout


@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:acme/widgets.git",
        "https://github.com/acme/widgets.git",
        "https://github.com/acme/widgets",
    ],
)
def test_repo_slug_reads_every_github_remote_spelling(tmp_path, remote):
    checkout = _repo(tmp_path, remote=remote)

    assert lane.repo_slug(checkout) == "acme/widgets"


def test_repo_slug_refuses_a_non_github_remote(tmp_path):
    checkout = _repo(tmp_path, remote="https://gitlab.com/acme/widgets.git")

    with pytest.raises(QaCaseExecutionError, match="not a GitHub repository"):
        lane.repo_slug(checkout)


def test_lane_branch_prefers_the_case_lane(tmp_path):
    checkout = _repo(tmp_path, remote="git@github.com:acme/widgets.git")

    assert lane.lane_branch({"lane_branch": "PRJ-9"}, checkout) == "PRJ-9"


def test_lane_branch_falls_back_to_the_checkout_branch(tmp_path):
    checkout = _repo(tmp_path, remote="git@github.com:acme/widgets.git")

    assert lane.lane_branch({"lane_branch": None}, checkout) == "trunk"
    # The context serializes a missing lane as the string "null".
    assert lane.lane_branch({"lane_branch": "null"}, checkout) == "trunk"


def test_lane_branch_refuses_a_detached_head(tmp_path):
    checkout = _repo(tmp_path, remote="git@github.com:acme/widgets.git")
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(checkout), "checkout", "-q", "--detach", head],
        check=True,
    )

    with pytest.raises(QaCaseExecutionError, match="detached HEAD"):
        lane.lane_branch({}, checkout)


def test_push_lane_publishes_the_head_under_the_lane_name(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    checkout = _repo(tmp_path, remote=str(origin))

    lane.push_lane(checkout, "PRJ-9")

    published = subprocess.run(
        ["git", "-C", str(origin), "rev-parse", "refs/heads/PRJ-9"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    local = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert published == local


def test_push_lane_reports_a_failed_push(tmp_path):
    checkout = _repo(tmp_path, remote=str(tmp_path / "missing.git"))

    with pytest.raises(QaCaseExecutionError, match="pushing lane branch"):
        lane.push_lane(checkout, "PRJ-9")


def test_workflow_file_requires_a_declaration():
    with pytest.raises(QaCaseExecutionError, match="ci_workflow_file"):
        lane.workflow_file({"method_config": {"command": "pytest"}})

    assert lane.workflow_file(
        {"method_config": {"ci_workflow": "ci.yml"}}
    ) == "ci.yml"


def test_authority_uses_the_active_https_connection(monkeypatch):
    from yoke_core.domain.deploy_pipeline_reporting import (
        GITHUB_ACTIONS_RELAY_ENV,
    )

    monkeypatch.delenv(GITHUB_ACTIONS_RELAY_ENV, raising=False)
    monkeypatch.delenv(lane.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, raising=False)
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda *a, **k: type("C", (), {"env": "prod"})(),
    )

    with lane.github_actions_authority():
        assert os.environ[GITHUB_ACTIONS_RELAY_ENV] == "prod"
    # Derived selection is scoped to the run; it never leaks outward.
    assert GITHUB_ACTIONS_RELAY_ENV not in os.environ


def test_authority_leaves_an_explicit_selection_alone(monkeypatch):
    from yoke_core.domain.deploy_pipeline_reporting import (
        GITHUB_ACTIONS_RELAY_ENV,
    )

    monkeypatch.setenv(GITHUB_ACTIONS_RELAY_ENV, "stage")

    def _unexpected(*args, **kwargs):
        raise AssertionError("explicit selection must win")

    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection", _unexpected,
    )

    with lane.github_actions_authority():
        assert os.environ[GITHUB_ACTIONS_RELAY_ENV] == "stage"
    assert os.environ[GITHUB_ACTIONS_RELAY_ENV] == "stage"


def test_authority_under_a_db_admin_connection_uses_its_own_https_plane(
    monkeypatch,
):
    """A direct-Postgres connection asks the plane it administers.

    The deploy layer's fallback would pick an independently deployed peer,
    which holds neither this project's rows nor its App authorization.
    """
    from yoke_core.domain.deploy_pipeline_reporting import (
        GITHUB_ACTIONS_RELAY_ENV,
    )

    monkeypatch.delenv(GITHUB_ACTIONS_RELAY_ENV, raising=False)
    monkeypatch.delenv(lane.GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, raising=False)
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.load_config",
        lambda *a, **k: {
            "connections": {
                "prod": {"transport": "https"},
                "prod-db-admin": {"transport": "local-postgres"},
                "stage": {"transport": "https"},
            }
        },
    )
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.active_env",
        lambda *a, **k: "prod-db-admin",
    )

    with lane.github_actions_authority():
        assert os.environ[GITHUB_ACTIONS_RELAY_ENV] == "prod"
    assert GITHUB_ACTIONS_RELAY_ENV not in os.environ


def test_run_head_sha_reads_through_the_relay(monkeypatch):
    """The head-sha read reaches GitHub the way dispatch and polling do."""
    import json

    seen: dict = {}

    def _fake_github_actions(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        body = json.dumps({"success": True, "result": {"head_sha": "a" * 40}})
        return subprocess.CompletedProcess(list(args), 0, body, "")

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        _fake_github_actions,
    )

    assert lane.run_head_sha(
        project="yoke", repo="acme/widgets", run_id="55",
    ) == "a" * 40
    assert seen["args"] == ("poll", "acme/widgets", "55", "--json")
    assert seen["kwargs"]["project"] == "yoke"


def test_run_head_sha_reports_a_control_plane_without_the_field(monkeypatch):
    """A plane predating the field answers empty, not with an error."""
    import json

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *a, **k: subprocess.CompletedProcess(
            list(a), 0,
            json.dumps({"success": True, "result": {"state": "success"}}),
            "",
        ),
    )

    assert lane.run_head_sha(
        project="yoke", repo="acme/widgets", run_id="55",
    ) == ""


def test_run_head_sha_raises_when_the_relay_refuses(monkeypatch):
    import json

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *a, **k: subprocess.CompletedProcess(
            list(a), 4,
            json.dumps({"success": False}),
            "no GitHub Actions authority selected",
        ),
    )

    with pytest.raises(QaCaseExecutionError, match="no GitHub Actions authority"):
        lane.run_head_sha(project="yoke", repo="acme/widgets", run_id="55")


def test_dispatch_passes_the_correlation_input_and_returns_the_run_id(monkeypatch):
    seen: dict = {}

    def _fake_github_actions(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(list(args), 0, "9182736", "")

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        _fake_github_actions,
    )

    run_id = lane.dispatch_workflow(
        project="yoke", repo="acme/widgets", workflow="ci.yml",
        branch="PRJ-9", request_id="qa-case:7:abc", timeout_seconds=60,
    )

    assert run_id == "9182736"
    args = seen["args"]
    assert args[0] == "trigger"
    assert "--ref" in args and "PRJ-9" in args
    assert "--request-id" in args and "qa-case:7:abc" in args
    assert "--correlation-input" in args and "yoke_dispatch_id" in args


def test_dispatch_reports_a_refused_trigger(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *a, **k: subprocess.CompletedProcess(
            list(a), 1, "", "workflow not found",
        ),
    )

    with pytest.raises(QaCaseExecutionError, match="workflow not found"):
        lane.dispatch_workflow(
            project="yoke", repo="acme/widgets", workflow="ci.yml",
            branch="PRJ-9", request_id="qa-case:7:abc", timeout_seconds=1,
        )


@pytest.mark.parametrize(
    ("status", "state_filter"),
    [("completed", ("--status", "completed")), ("", ())],
)
def test_pull_request_lookup_uses_exact_run_filters(
    monkeypatch, status, state_filter,
):
    seen: dict = {}

    def _fake_github_actions(*args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        body = {
            "result": {
                "found": True,
                "run_id": "77",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.test/actions/runs/77",
                "head_sha": "a" * 40,
            }
        }
        return subprocess.CompletedProcess(list(args), 0, json.dumps(body), "")

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        _fake_github_actions,
    )
    run = lane.find_pull_request_run(
        project="yoke", repo="acme/widgets", workflow="ci.yml",
        head_sha="a" * 40, timeout_seconds=60, status=status,
    )

    assert run == lane.WorkflowRun(
        "77", "completed", "success",
        "https://github.test/actions/runs/77", "a" * 40,
    )
    assert seen["args"] == (
        "find-run", "acme/widgets", "ci.yml", "a" * 40,
        "--event", "pull_request", *state_filter, "--json",
    )


def test_pull_request_lookup_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions",
        lambda *a, **k: subprocess.CompletedProcess(
            list(a), 1, json.dumps({"result": {"found": False}}), "",
        ),
    )

    assert lane.find_pull_request_run(
        project="yoke", repo="acme/widgets", workflow="ci.yml",
        head_sha="a" * 40, timeout_seconds=60,
    ) is None
