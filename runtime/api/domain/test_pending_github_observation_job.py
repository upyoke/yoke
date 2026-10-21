"""GitHub observation runs as a background job, never inside a relay claim."""

from __future__ import annotations

import logging
import threading

from yoke_core.domain import gh_rest_transport
from yoke_core.domain import merge_queue_landing_observer
from yoke_core.domain import pending_github_observation_job as job
from yoke_core.domain import session_ci_wait_observer
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import NOW, relay_connection


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=f"machine:{MACHINE_ID}",
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )


def _refuse(calls: list[str], name: str):
    def refuse(*_args, **_kwargs):
        calls.append(name)
        raise RuntimeError(f"{name} must not run during a relay claim")

    return refuse


def test_relay_claim_makes_no_github_call(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(gh_rest_transport, "urlopen", _refuse(calls, "github"))
    monkeypatch.setattr(
        merge_queue_landing_observer,
        "observe_pending_landings",
        _refuse(calls, "landings"),
    )
    monkeypatch.setattr(
        session_ci_wait_observer,
        "observe_pending_ci_runs",
        _refuse(calls, "ci_runs"),
    )
    monkeypatch.setattr(job, "observe_pending_landings", _refuse(calls, "landings"))
    monkeypatch.setattr(job, "observe_pending_ci_runs", _refuse(calls, "ci_runs"))

    outcome = claim_relay_job(
        relay_connection(), _heartbeat(), wait_seconds=0, now_provider=lambda: NOW
    )

    assert outcome.state in {"active", "idle"}
    assert calls == []


def test_job_cycle_runs_both_observers_over_every_project(monkeypatch) -> None:
    conn = relay_connection()
    conn.execute("INSERT INTO projects (id, slug) VALUES (20, 'second-project')")
    conn.commit()
    seen: dict[str, tuple[int, ...]] = {}

    def landings(_conn, projects, *, now):
        seen["landings"] = tuple(projects)
        return {"checked": 1}

    def ci_runs(_conn, projects, *, now):
        seen["ci_runs"] = tuple(projects)
        return {"checked": 2, "errors": []}

    monkeypatch.setattr(job, "observe_pending_landings", landings)
    monkeypatch.setattr(job, "observe_pending_ci_runs", ci_runs)

    result = job.observe_pending_github_work(conn)

    assert seen == {"landings": (10, 20), "ci_runs": (10, 20)}
    assert result["landings"] == {"checked": 1}
    assert result["ci_runs"]["checked"] == 2


def test_failing_observer_spares_the_other_and_is_logged(monkeypatch, caplog) -> None:
    ran: list[str] = []

    def landings(*_args, **_kwargs):
        raise RuntimeError("github unavailable")

    def ci_runs(*_args, **_kwargs):
        ran.append("ci_runs")
        return {"errors": ["wait 7: run unreadable"]}

    monkeypatch.setattr(job, "observe_pending_landings", landings)
    monkeypatch.setattr(job, "observe_pending_ci_runs", ci_runs)

    with caplog.at_level(logging.WARNING, logger=job.__name__):
        result = job.observe_pending_github_work(relay_connection())

    assert ran == ["ci_runs"]
    assert result["landings"] == {"error": "github unavailable"}
    assert "pending landing observation failed: github unavailable" in caplog.text
    assert "pending CI run observation failed: wait 7: run unreadable" in caplog.text


def test_failed_cycle_is_logged_and_the_job_keeps_running(monkeypatch, caplog) -> None:
    from yoke_core.domain import db_helpers

    def unreachable(*_args, **_kwargs):
        raise OSError("database unreachable")

    monkeypatch.setattr(db_helpers, "connect", unreachable)

    with caplog.at_level(logging.WARNING, logger=job.__name__):
        job.run_observation_cycle()

    assert "pending GitHub observation cycle failed" in caplog.text


def test_job_runs_cycles_off_the_caller_thread_and_stops() -> None:
    cycles: list[threading.Thread] = []
    second = threading.Event()

    def cycle() -> None:
        cycles.append(threading.current_thread())
        if len(cycles) == 2:
            second.set()

    with job.pending_github_observation_job(interval_seconds=0.01, cycle=cycle):
        assert second.wait(1)
    assert cycles[0] is not threading.current_thread()
    assert not cycles[0].is_alive()


def test_job_waits_one_interval_before_its_first_cycle() -> None:
    cycles: list[str] = []

    with job.pending_github_observation_job(
        interval_seconds=60, cycle=lambda: cycles.append("cycle")
    ):
        pass

    assert cycles == []


def test_api_server_lifespan_hosts_github_observation(monkeypatch) -> None:
    from contextlib import contextmanager, nullcontext

    from fastapi.testclient import TestClient

    import yoke_core.api.main  # noqa: F401 - app-factory import anchor
    from yoke_core.api import app_factory
    from runtime.api.fixtures import pg_testdb

    hosting: list[bool] = []

    @contextmanager
    def hosted_job():
        hosting.append(True)
        yield
        hosting.append(False)

    monkeypatch.setattr(job, "pending_github_observation_job", hosted_job)
    monkeypatch.setattr(
        "yoke_core.api.health_refresh.health_refresh_lifespan", nullcontext
    )
    with pg_testdb.test_database(), TestClient(app_factory.create_app()):
        assert hosting == [True]
    assert hosting == [True, False]
