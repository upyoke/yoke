"""A dispatch never runs source subprocesses or HTTP with an open transaction."""

import base64
import io
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
from psycopg.pq import TransactionStatus
import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_release_version import (
    _pin_capability,
    _stage,
    PIN_FILE,
    PINNED,
)
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_transaction_recovery import rollback_after_error
from yoke_core.domain.connected_env_readiness_connector import (
    looks_like_connection_failure,
)


@pytest.mark.parametrize("source", ["checkout", "provider"])
def test_dispatch_external_inputs_are_idle_and_read_once(
    test_db, monkeypatch, tmp_path, source
):
    stage = _stages(_plan(test_db))
    _seed_run(
        test_db,
        run_id="run-transaction-free",
        stages=stage,
        members=tuple(range(9301, 9309)),
    )
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db)
    calls = {"git": 0, "provider": 0, "http": 0}

    def idle():
        assert test_db.info.transaction_status == TransactionStatus.IDLE

    def git(*args, **kwargs):
        idle()
        calls["git"] += 1
        return SimpleNamespace(
            returncode=0 if source == "checkout" else 1,
            stdout=PINNED.encode(),
            stderr=b"unavailable",
        )

    def provider(*args, **kwargs):
        idle()
        calls["provider"] += 1
        return SimpleNamespace(
            body={
                "encoding": "base64",
                "content": base64.b64encode(PINNED.encode()).decode(),
            }
        )

    def auth(*args, conn, **kwargs):
        conn.execute("SELECT 1")
        idle()
        return SimpleNamespace(repo="example/project", token="fixture-token")

    def http(*args, **kwargs):
        idle()
        calls["http"] += 1
        return io.BytesIO(b'[{"filename":"wheel.whl"}]')

    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
        lambda _: tmp_path,
    )
    monkeypatch.setattr("yoke_core.domain.project_file_at_commit.subprocess.run", git)
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth", auth
    )
    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.request_with_retry", provider
    )
    monkeypatch.setattr("urllib.request.urlopen", http)
    result = materialize_and_gate_deployment_qa_stage(
        test_db, stage[-1], run_id="run-transaction-free"
    )
    assert result[0] == -4
    assert calls == {
        "git": 1 if source == "checkout" else 2,
        "provider": int(source == "provider"),
        "http": 1,
    }
    assert test_db.autocommit is False


def test_failed_rollback_keeps_original_error_in_lost_connection_outcome():
    conn = Mock()
    conn.rollback.side_effect = psycopg.OperationalError("the connection is closed")
    original = psycopg.OperationalError(
        "terminating connection due to idle-in-transaction timeout"
    )
    with pytest.raises(psycopg.OperationalError) as raised:
        rollback_after_error(conn, original)
    assert looks_like_connection_failure(raised.value)
    assert (
        "original OperationalError: terminating connection due to idle-in-transaction timeout"
        in str(raised.value)
    )
    assert raised.value.__cause__ is original


def test_unprepared_external_read_refuses_before_starting_a_subprocess(
    test_db, monkeypatch
):
    from yoke_core.domain.deployment_qa_dispatch_inputs import dispatch_input_operation
    from yoke_core.domain.project_file_at_commit import read_project_file

    subprocess = Mock()
    monkeypatch.setattr(
        "yoke_core.domain.project_file_at_commit.subprocess.run", subprocess
    )
    test_db.execute("SELECT 1")

    @dispatch_input_operation
    def read(conn):
        return read_project_file(conn, 1, "a" * 40, PIN_FILE)

    with pytest.raises(ValueError, match="deployment_qa_source_inputs_changed"):
        read(test_db)
    subprocess.assert_not_called()


def test_rollback_loss_envelope_surfaces_the_triggering_timeout():
    from runtime.api.domain.test_session_less_actor_binding import _entry, _request
    from yoke_core.domain.function_connection_loss import (
        name_connection_loss,
        CONNECTION_LOST_CODE,
    )

    conn = Mock()
    conn.rollback.side_effect = psycopg.OperationalError("the connection is closed")
    original = psycopg.errors.IdleInTransactionSessionTimeout(
        "terminating connection due to idle-in-transaction timeout"
    )
    outcome = name_connection_loss(
        _entry(), _request(), lambda *args: rollback_after_error(conn, original)
    )
    assert outcome.error.code == CONNECTION_LOST_CODE
    assert "original IdleInTransactionSessionTimeout" in outcome.error.message
    assert "idle-in-transaction timeout" in outcome.error.message


def test_unpublished_prepared_input_returns_the_named_stage_failure(
    test_db, monkeypatch, tmp_path
):
    stages = _stages(_plan(test_db))
    _seed_run(test_db, run_id="run-unpublished-input", stages=stages, members=(9401,))
    _pin_capability(test_db, candidate_pin_file=PIN_FILE)
    _stage(test_db)
    monkeypatch.setattr(
        "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
        lambda _: tmp_path,
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_file_at_commit.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=PINNED.encode(), stderr=b""
        ),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: io.BytesIO(b"[]"))
    code, reason = materialize_and_gate_deployment_qa_stage(
        test_db, stages[-1], run_id="run-unpublished-input"
    )
    assert code == 1
    assert "deployment_qa_release_unpublished" in reason
    assert "publish Yoke" in reason
    assert "re-run the QA stage" in reason
