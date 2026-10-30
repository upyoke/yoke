"""Repository authority and sync-receipt isolation for CI observation."""

from __future__ import annotations

import io
import urllib.error
from types import SimpleNamespace

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import message_count
from runtime.api.domain.test_session_ci_wait_observer import (
    NOW,
    waiting_connection as waiting_connection,
)
from yoke_contracts.timestamps import format_instant
from yoke_core.domain import (
    gh_rest_transport,
    project_github_auth,
    project_github_sync_receipt as receipts,
)
from yoke_core.domain.session_ci_wait_observer import (
    observe_pending_ci_runs,
    read_run_conclusion,
)


def test_cross_project_wait_uses_repository_project_token(waiting_connection, monkeypatch):
    conn = waiting_connection
    conn.executescript(
        "INSERT INTO projects (id,org_id,slug,name,public_item_prefix) "
        "VALUES (9,1,'other','Other','OTHER');"
        "UPDATE project_github_repo_bindings SET project_id=9, "
        "github_repo='ACME/Widgets';"
    )
    calls = []

    def auth(project, **kwargs):
        assert project == 'other'
        return SimpleNamespace(token='repository-token')

    def rest_get(path, *, token):
        calls.append((path, token))
        return {'status': 'completed', 'conclusion': 'success'}

    monkeypatch.setattr(project_github_auth, 'resolve_project_github_auth', auth)
    monkeypatch.setattr('yoke_core.domain.github_actions_rest.rest_get', rest_get)
    result = observe_pending_ci_runs(conn, [1], now=NOW)

    assert not result['errors']
    assert calls == [('/repos/acme/widgets/actions/runs/33903192687', 'repository-token')]
    row = conn.execute('SELECT project_id, conclusion FROM session_ci_run_waits').fetchone()
    assert dict(row) == {'project_id': 1, 'conclusion': 'success'}
    assert message_count(conn) == 1


@pytest.mark.parametrize('binding_status', [None, 'revoked'])
@pytest.mark.parametrize('conclusion', ['', 'failure'])
def test_unbound_repo_settles_without_read_or_notice(
    waiting_connection, binding_status, conclusion
):
    conn = waiting_connection
    if binding_status is None:
        conn.execute('DELETE FROM project_github_repo_bindings')
    else:
        conn.execute('UPDATE project_github_repo_bindings SET status=?', (binding_status,))
    conn.execute('UPDATE session_ci_run_waits SET conclusion=?', (conclusion,))
    conn.commit()

    def refuse(*args):
        raise AssertionError('unbound repository must not be read')

    result = observe_pending_ci_runs(conn, [1], now=NOW, read_run=refuse)

    assert not result['errors']
    row = conn.execute('SELECT conclusion, notified_at FROM session_ci_run_waits').fetchone()
    assert dict(row) == {'conclusion': 'repo_unbound', 'notified_at': format_instant(NOW)}
    assert message_count(conn) == 0
    assert observe_pending_ci_runs(conn, [1], now=NOW, read_run=refuse)['checked'] == 0


class RunResponse:
    status = 200
    headers = {'Content-Type': 'application/json'}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        body = b'{"status":"completed","conclusion":"success"}'
        return body if size < 0 else body[:size]


@pytest.mark.parametrize('failed', [False, True])
def test_ci_reads_leave_receipt_fields_unchanged(waiting_connection, monkeypatch, failed):
    conn = waiting_connection
    conn.executescript(
        "ALTER TABLE project_github_repo_bindings ADD COLUMN last_sync_at TEXT;"
        "ALTER TABLE project_github_repo_bindings ADD COLUMN last_sync_outcome TEXT;"
        "ALTER TABLE project_github_repo_bindings ADD COLUMN last_sync_error TEXT;"
        "UPDATE project_github_repo_bindings SET last_sync_at='2026-09-01T00:00:00Z', "
        "last_sync_outcome='success', last_sync_error='';"
    )
    before = dict(conn.execute('SELECT * FROM project_github_repo_bindings').fetchone())
    receipts.register_installation_token('poll-token', 'acme')
    monkeypatch.setattr(
        project_github_auth, 'resolve_project_github_auth',
        lambda *args, **kwargs: SimpleNamespace(token='poll-token'),
    )
    writes = []

    def record(*args, **kwargs):
        writes.append(kwargs)
        conn.execute("UPDATE project_github_repo_bindings SET last_sync_outcome='failed'")
        return True

    monkeypatch.setattr(receipts.control_plane_transport, 'local_connection_or_none', lambda f: conn)
    monkeypatch.setattr(receipts, 'record_over_connection', record)

    def respond(*args, **kwargs):
        if failed:
            raise urllib.error.HTTPError(
                'https://api.github.com/repos/acme/widgets/actions/runs/1',
                404, 'missing', {'Content-Type': 'application/json'},
                io.BytesIO(b'{"message":"Not Found"}'),
            )
        return RunResponse()

    monkeypatch.setattr(gh_rest_transport, 'urlopen', respond)
    status, conclusion, error = read_run_conclusion('acme', 'acme/widgets', '1')

    assert bool(error) is failed
    if not failed:
        assert (status, conclusion) == ('completed', 'success')
    assert writes == []
    assert dict(conn.execute('SELECT * FROM project_github_repo_bindings').fetchone()) == before


def test_receipt_suppression_restores_nested_context_after_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(receipts, '_token_digest', lambda token: calls.append(token) or '')
    with receipts.suppress_installation_token_receipts():
        with pytest.raises(ValueError), receipts.suppress_installation_token_receipts():
            raise ValueError('read failed')
        assert receipts.record_installation_token_result('inner', outcome='success') is False
    assert receipts.record_installation_token_result('outer', outcome='success') is False
    assert calls == ['outer']
