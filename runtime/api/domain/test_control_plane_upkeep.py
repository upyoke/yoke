"""Control-plane upkeep reads GitHub and replays owed settlements, never in a relay claim."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from yoke_core.domain import gh_rest_transport
from yoke_core.domain import merge_queue_landing_observer
from yoke_core.domain import control_plane_upkeep as job
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


def test_upkeep_runs_both_steps_on_one_connection_and_closes_it(monkeypatch) -> None:
    from yoke_core.domain import db_helpers

    closed: list[bool] = []
    conn = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(db_helpers, "connect", lambda: conn)
    ran: list[tuple[str, object]] = []
    monkeypatch.setattr(
        job, "observe_pending_github_work", lambda c: ran.append(("github", c))
    )
    monkeypatch.setattr(
        job, "replay_settlement_followups", lambda c: ran.append(("settlement", c))
    )

    job.run_control_plane_upkeep()

    assert ran == [("github", conn), ("settlement", conn)]
    assert closed == [True]


def test_failing_step_spares_the_next_and_is_logged(monkeypatch, caplog) -> None:
    from yoke_core.domain import db_helpers

    monkeypatch.setattr(db_helpers, "connect", relay_connection)
    ran: list[str] = []

    def github(_conn):
        raise RuntimeError("github unavailable")

    monkeypatch.setattr(job, "observe_pending_github_work", github)
    monkeypatch.setattr(
        job, "replay_settlement_followups", lambda _c: ran.append("settlement")
    )

    with caplog.at_level(logging.WARNING, logger=job.__name__):
        job.run_control_plane_upkeep()

    assert ran == ["settlement"]
    assert "pending GitHub observation failed" in caplog.text
    assert "github unavailable" in caplog.text


def test_unreachable_database_is_logged_and_upkeep_returns(monkeypatch, caplog) -> None:
    from yoke_core.domain import db_helpers

    def unreachable(*_args, **_kwargs):
        raise OSError("database unreachable")

    monkeypatch.setattr(db_helpers, "connect", unreachable)

    with caplog.at_level(logging.WARNING, logger=job.__name__):
        job.run_control_plane_upkeep()

    assert "control-plane upkeep could not connect" in caplog.text


def test_api_server_starts_no_upkeep_thread_of_its_own(monkeypatch) -> None:
    import threading
    from contextlib import nullcontext

    from fastapi.testclient import TestClient

    import yoke_core.api.main  # noqa: F401 - app-factory import anchor
    from yoke_core.api import app_factory
    from runtime.api.fixtures import pg_testdb

    monkeypatch.setattr(
        "yoke_core.api.health_refresh.health_refresh_lifespan", nullcontext
    )
    before = {thread.ident for thread in threading.enumerate()}
    with pg_testdb.test_database(), TestClient(app_factory.create_app()):
        started = [
            thread.name
            for thread in threading.enumerate()
            if thread.ident not in before and thread.name.startswith("yoke-")
        ]
    assert started == []
