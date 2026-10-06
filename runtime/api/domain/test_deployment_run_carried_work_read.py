"""Current carried-work presentation preserves durable records and bounds cost."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from yoke_core.domain import deployment_run_carried_work_read as subject


@pytest.fixture(autouse=True)
def clear_cache():
    subject._CACHE.clear()
    yield
    subject._CACHE.clear()


def connection(database="tenant"):
    return SimpleNamespace(
        info=SimpleNamespace(
            host="localhost",
            port=5432,
            dbname=database,
            user="reader",
        )
    )


def run(**changes):
    return {
        "id": "run-current",
        "status": "executing",
        "carried_work": None,
        "release_lineage": "a" * 40,
        **changes,
    }


def test_current_work_is_cached_across_connections_and_defensively_copied():
    payload = {"items": [{"ref": "ITEM-1"}]}
    with patch.object(
        subject, "derive_carried_work_safely", return_value=payload
    ) as derive:
        first = subject.read_carried_work(connection(), run())
        first["items"].clear()
        second = subject.read_carried_work(connection(), run())
    assert second["items"] == [{"ref": "ITEM-1"}]
    derive.assert_called_once()


def test_recorded_work_immediately_replaces_a_cached_answer():
    with patch.object(
        subject, "derive_carried_work_safely", return_value={"items": []}
    ) as derive:
        subject.read_carried_work(connection(), run())
        recorded = {"items": [{"ref": "ITEM-2"}]}
        result = subject.read_carried_work(
            connection(), run(status="succeeded", carried_work=recorded)
        )
    assert result == recorded
    derive.assert_called_once()


def test_cache_expires_and_separates_authorities_runs_and_pinned_sources():
    with (
        patch.object(subject, "monotonic", return_value=0) as clock,
        patch.object(
            subject, "derive_carried_work_safely", return_value={"items": []}
        ) as derive,
    ):
        subject.read_carried_work(connection(), run())
        subject.read_carried_work(connection("other"), run())
        subject.read_carried_work(connection(), run(id="run-other"))
        subject.read_carried_work(connection(), run(release_lineage="b" * 40))
        subject.read_carried_work(
            connection(), run(bound_sources={"consumer": "c" * 40})
        )
        assert derive.call_count == 5
        clock.return_value = subject.CACHE_SECONDS
        subject.read_carried_work(connection(), run())
        assert derive.call_count == 6


def test_cache_is_bounded():
    with (
        patch.object(subject, "CACHE_RUN_LIMIT", 2),
        patch.object(
            subject, "derive_carried_work_safely", return_value={"items": []}
        ) as derive,
    ):
        for number in range(3):
            subject.read_carried_work(connection(), run(id=str(number)))
        assert len(subject._CACHE) == 2
        subject.read_carried_work(connection(), run(id="0"))
        assert derive.call_count == 4


def test_compact_work_keeps_bound_project_item_routes_and_derivation():
    result = subject.compact_carried_work(
        {
            "items": [],
            "commits": ["a" * 40],
            "commit_subjects": {"a" * 40: "Maintenance"},
            "commit_authors": {"a" * 40: "A maintainer"},
            "bound_projects": [
                {
                    "project_id": 2,
                    "project": "consumer",
                    "items": [{"ref": "CON-1", "item_id": 10, "project_sequence": 1}],
                    "derivation": {"status": "derived", "contents_known": True},
                }
            ],
        }
    )
    assert result["commits"] == ["a" * 40]
    assert result["commit_subjects"]["a" * 40] == "Maintenance"
    assert result["commit_authors"]["a" * 40] == "A maintainer"
    assert result["bound_projects"][0]["project_id"] == 2
    assert result["bound_projects"][0]["items"][0]["project_sequence"] == 1
    assert result["bound_projects"][0]["derivation"]["contents_known"] is True


def test_unfinished_run_is_derived_without_recording():
    conn = Mock(info=None)
    with patch.object(
        subject, "derive_carried_work_safely", return_value={"items": []}
    ):
        assert subject.read_carried_work(conn, run()) == {"items": []}
    conn.execute.assert_not_called()


KNOWN = {"derivation": {"contents_known": True}, "items": []}
TRANSIENT = {
    "derivation": {"contents_known": False, "reason": "project_source_unavailable"},
    "items": [],
}


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_unsaved_terminal_run_is_recorded_not_derived_live(status):
    conn = Mock(info=None)
    with (
        patch.object(subject, "record_carried_work", return_value=KNOWN) as record,
        patch.object(subject, "derive_carried_work_safely") as derive,
    ):
        assert subject.read_carried_work(conn, run(status=status)) == KNOWN
    record.assert_called_once_with(conn, "run-current", permanent_only=True)
    conn.commit.assert_called_once_with()
    derive.assert_not_called()
    assert not subject._CACHE


def test_transient_terminal_answer_is_cached_then_retried():
    conn = Mock(info=connection().info)
    with (
        patch.object(subject, "monotonic", return_value=0) as clock,
        patch.object(subject, "record_carried_work", return_value=TRANSIENT) as record,
    ):
        assert subject.read_carried_work(conn, run(status="failed")) == TRANSIENT
        subject.read_carried_work(conn, run(status="failed"))
        assert record.call_count == 1
        clock.return_value = subject.CACHE_SECONDS
        subject.read_carried_work(conn, run(status="failed"))
    assert record.call_count == 2


def test_permanent_terminal_answer_is_not_cached():
    conn = Mock(info=connection().info)
    with patch.object(subject, "record_carried_work", return_value=KNOWN):
        subject.read_carried_work(conn, run(status="cancelled"))
    assert not subject._CACHE


def test_concurrent_cold_reads_of_a_live_run_derive_once():
    started = Event()
    release = Event()

    def slow_derive(_conn, _run_id):
        started.set()
        release.wait(5)
        return {"items": []}

    with patch.object(
        subject, "derive_carried_work_safely", side_effect=slow_derive
    ) as derive:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(subject.read_carried_work, connection(), run())
            assert started.wait(5)
            second = pool.submit(subject.read_carried_work, connection(), run())
            release.set()
            assert first.result(5) == second.result(5) == {"items": []}
    derive.assert_called_once()
