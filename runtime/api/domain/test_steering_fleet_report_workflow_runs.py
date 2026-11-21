"""The next steering report surfaces a failed dispatch on the tested commit."""

from datetime import timedelta
from types import SimpleNamespace

from runtime.api.steering_fleet_test_helpers import NOW, PROJECT_ID, compose, seed_steering_scope
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import steering_fleet_report_workflow_runs as runs
from yoke_core.domain.schema_connection import instant_parameter
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body, scope_actionable_digest


def _dispatch(conn, run_id, scope, commit, created, updated=None):
    conn.execute(
        "INSERT INTO github_workflow_dispatch_intents "
        "(request_id, attempt, actor_id, authorization_scope, payload_checksum, "
        "repo, workflow, workflow_ref, inputs, correlation_id, state, "
        "workflow_run_id, created_at, updated_at) "
        "VALUES (%s, 1, '2', %s, 'checksum', 'owner/repo', 'yoke-suite.yml', "
        "'main', %s, %s, 'completed', %s, %s, %s)",
        (
            run_id, scope, f'{{"sha":"{commit}"}}', run_id, run_id,
            instant_parameter(conn, created), instant_parameter(conn, updated or created),
        ),
    )


def _stub_auth(monkeypatch):
    monkeypatch.setattr(
        runs, "resolve_project_github_auth",
        lambda *args, **kwargs: SimpleNamespace(repo="owner/repo", token="test"),
    )


def test_report_reads_new_verdict_on_next_poll(test_db, monkeypatch):
    conn = seed_steering_scope(test_db)
    commit = "1" * 40
    created = parse_instant(NOW) - timedelta(minutes=2)
    for run_id, scope in (("42", f"project:{PROJECT_ID}"), ("43", "project:99999")):
        _dispatch(conn, run_id, scope, commit, created)
    conn.commit()
    _stub_auth(monkeypatch)
    remote = {"id": 42, "status": "in_progress", "head_sha": "2" * 40}

    def get_run(request, **kwargs):
        assert request.path == "/repos/owner/repo/actions/workflows/yoke-suite.yml/runs"
        assert request.method == "GET"
        return SimpleNamespace(body={"workflow_runs": [dict(remote)]})

    monkeypatch.setattr(runs.gh_rest_transport, "request_with_retry", get_run)
    running = compose(conn)
    assert not running.suite_runs

    remote.update(status="completed", conclusion="failure")
    failed = compose(conn)
    [row] = failed.suite_runs
    assert (row.run_id, row.commit, row.conclusion) == ("42", commit, "failure")
    assert failed.actionable
    assert failed.fingerprint() != running.fingerprint()
    finding = f"owner/repo run 42, commit {commit}: failure"
    assert finding in report_body(failed)
    assert finding in scope_actionable_digest(failed)
    assert report_dict(failed)["suite_runs"][0]["commit"] == commit

    remote.update(conclusion="success")
    assert not compose(conn).suite_runs


def test_suite_findings_use_one_listing_and_report_unreadable_runs(test_db, monkeypatch):
    conn = seed_steering_scope(test_db)
    now = parse_instant(NOW)
    oldest = now - timedelta(minutes=4)
    commit = "1" * 40
    scope = f"project:{PROJECT_ID}"
    for run_id in range(42, 46):
        _dispatch(conn, str(run_id), scope, commit,
                  oldest + timedelta(minutes=run_id - 42), updated=now)
    conn.commit()
    _stub_auth(monkeypatch)
    requests = []
    listing = [
        {"id": 43, "status": "in_progress"},
        {"id": 42, "status": "completed", "conclusion": "cancelled"},
        {"id": 44, "status": "completed", "conclusion": "success"},
    ]

    def get_runs(request, **kwargs):
        requests.append(request)
        return SimpleNamespace(body={"workflow_runs": listing})

    monkeypatch.setattr(runs.gh_rest_transport, "request_with_retry", get_runs)
    cancelled, missing = runs.suite_run_findings(conn, project_id=PROJECT_ID, now=now)
    [request] = requests
    assert request.method == "GET"
    assert request.path == "/repos/owner/repo/actions/workflows/yoke-suite.yml/runs"
    assert request.query == {
        "event": "workflow_dispatch", "per_page": "100",
        "created": f">={format_instant(oldest)}",
    }
    assert cancelled == runs.SuiteRunFinding(
        "owner/repo", "42", commit, "cancelled",
        f"yoke github-actions wait-run owner/repo 42 --project {PROJECT_ID}",
    )
    assert missing.run_id == "45" and missing.conclusion == "unreadable"
    assert "omitted run 45" in missing.recovery
    assert "yoke github-actions wait-run owner/repo 45" in missing.recovery

    def unreachable(request, **kwargs):
        requests.append(request)
        raise runs.gh_rest_transport.RestTransportError("GitHub unavailable")

    listing.append(None)
    invalid = runs.suite_run_findings(conn, project_id=PROJECT_ID, now=now)
    monkeypatch.setattr(runs.gh_rest_transport, "request_with_retry", unreachable)
    unavailable = runs.suite_run_findings(conn, project_id=PROJECT_ID, now=now)
    assert len(requests) == 3
    for findings, reason in ((invalid, "invalid workflow run"), (unavailable, "GitHub unavailable")):
        assert {row.run_id for row in findings} == {"42", "43", "44", "45"}
        assert all(row.conclusion == "unreadable" for row in findings)
        assert all(reason in row.recovery for row in findings)
        assert all(f"yoke github-actions wait-run owner/repo {row.run_id}" in row.recovery
                   for row in findings)
