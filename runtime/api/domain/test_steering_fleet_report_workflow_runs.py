"""The next steering report surfaces a failed dispatch on the tested commit."""

from datetime import timedelta
from types import SimpleNamespace

from runtime.api.steering_fleet_test_helpers import NOW, PROJECT_ID, compose, seed_steering_scope
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import steering_fleet_report_workflow_runs as runs
from yoke_core.domain.schema_connection import instant_parameter
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body, scope_actionable_digest


def test_report_reads_new_verdict_on_next_poll(test_db, monkeypatch):
    conn = seed_steering_scope(test_db)
    commit = "1" * 40
    created = instant_parameter(conn, parse_instant(NOW) - timedelta(minutes=2))
    for run_id, scope in (("42", f"project:{PROJECT_ID}"), ("43", "project:99999")):
        conn.execute(
            "INSERT INTO github_workflow_dispatch_intents "
            "(request_id, attempt, actor_id, authorization_scope, payload_checksum, "
            "repo, workflow, workflow_ref, inputs, correlation_id, state, "
            "workflow_run_id, created_at, updated_at) "
            "VALUES (%s, 1, '2', %s, 'checksum', 'owner/repo', 'yoke-suite.yml', "
            "'main', %s, %s, 'completed', %s, %s, %s)",
            (run_id, scope, f'{{"sha":"{commit}"}}', run_id, run_id, created, created),
        )
    conn.commit()
    monkeypatch.setattr(
        runs, "resolve_project_github_auth",
        lambda *args, **kwargs: SimpleNamespace(repo="owner/repo", token="test"),
    )
    remote = {"id": 42, "status": "in_progress", "head_sha": "2" * 40}

    def get_run(request, **kwargs):
        assert request.path == "/repos/owner/repo/actions/runs/42"
        assert request.method == "GET"
        return SimpleNamespace(body=dict(remote))

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
