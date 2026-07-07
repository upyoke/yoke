"""Tests for the Postgres readiness preflight (``wait_for_pg``).

Hermetic: the connection probe and sleep are injected, so no live cluster is
needed and the retry/backoff/exit logic is exercised deterministically.
"""

from __future__ import annotations

import pytest

from yoke_core.tools import wait_for_pg


def test_redact_dsn_masks_password_only():
    dsn = "host=localhost port=5432 user=yoke password=hunter2 dbname=postgres"
    redacted = wait_for_pg._redact_dsn(dsn)
    assert "password=***" in redacted
    assert "hunter2" not in redacted
    # Non-secret keys survive verbatim.
    assert "host=localhost" in redacted
    assert "user=yoke" in redacted
    assert "dbname=postgres" in redacted


def test_redact_dsn_is_case_insensitive_on_key():
    redacted = wait_for_pg._redact_dsn("PASSWORD=secret host=db")
    assert "secret" not in redacted
    assert "host=db" in redacted


def test_wait_succeeds_on_first_probe_without_sleeping():
    sleeps: list[float] = []
    probes: list[str] = []

    ready = wait_for_pg.wait_for_postgres(
        attempts=5,
        delay=0.1,
        dsn="host=db dbname=postgres",
        probe=lambda dsn: probes.append(dsn),
        sleep=sleeps.append,
        log=lambda _msg: None,
    )

    assert ready is True
    assert probes == ["host=db dbname=postgres"]
    assert sleeps == []  # no retry, no backoff


def test_wait_retries_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky_probe(_dsn: str) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("not ready yet")

    ready = wait_for_pg.wait_for_postgres(
        attempts=5,
        delay=0.25,
        dsn="host=db",
        probe=flaky_probe,
        sleep=sleeps.append,
        log=lambda _msg: None,
    )

    assert ready is True
    assert calls["n"] == 3
    # Slept after each of the two failures, not after the success.
    assert sleeps == [0.25, 0.25]


def test_wait_exhausts_attempts_and_reports_last_error():
    sleeps: list[float] = []
    messages: list[str] = []

    def always_fail(_dsn: str) -> None:
        raise RuntimeError("boom-547")

    ready = wait_for_pg.wait_for_postgres(
        attempts=4,
        delay=0.5,
        dsn="host=db password=topsecret",
        probe=always_fail,
        sleep=sleeps.append,
        log=messages.append,
    )

    assert ready is False
    # One sleep between each attempt, none after the final failure.
    assert sleeps == [0.5, 0.5, 0.5]
    assert len(messages) == 1
    # Failure message names the last error and redacts the password.
    assert "boom-547" in messages[0]
    assert "topsecret" not in messages[0]
    assert "password=***" in messages[0]


def test_wait_resolves_dsn_from_db_backend_when_not_supplied(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        wait_for_pg.db_backend,
        "resolve_pg_dsn",
        lambda dbname=None: f"host=resolved dbname={dbname}",
    )

    ready = wait_for_pg.wait_for_postgres(
        attempts=1,
        delay=0.0,
        probe=seen.append,
        sleep=lambda _s: None,
        log=lambda _m: None,
    )

    assert ready is True
    # Resolver was asked for the maintenance DB target.
    assert seen == [f"host=resolved dbname={wait_for_pg.MAINTENANCE_DBNAME}"]


@pytest.mark.parametrize("ready,expected_rc", [(True, 0), (False, 1)])
def test_main_exit_code_tracks_readiness(monkeypatch, ready, expected_rc):
    monkeypatch.setattr(
        wait_for_pg, "wait_for_postgres", lambda **_kwargs: ready
    )
    assert wait_for_pg.main([]) == expected_rc


def test_main_parses_attempts_and_delay(monkeypatch):
    captured: dict[str, object] = {}

    def fake_wait(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(wait_for_pg, "wait_for_postgres", fake_wait)
    rc = wait_for_pg.main(["--attempts", "7", "--delay", "2.5"])

    assert rc == 0
    assert captured["attempts"] == 7
    assert captured["delay"] == 2.5
