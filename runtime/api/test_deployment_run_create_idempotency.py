"""Keyed deployment-run creation: replay, conflict, and concurrent retries."""

from __future__ import annotations

import threading

import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.deployment_run_create_idempotency import (
    IdempotencyKeyConflict,
    canonical_request,
)
from yoke_core.domain.deployment_run_create_write import create_run

pytest_plugins = ["runtime.api.deployment_runs_test_db"]


def _request(**overrides: str) -> str:
    fields = {"project": "yoke", "flow": "flow-main", "created_by": "operator"}
    fields.update(overrides)
    return canonical_request(fields)


def _create(db_path: str, key: str | None, request: str, **kwargs):
    run_id, replayed, basis = create_run(
        "yoke",
        "flow-main",
        db_path=db_path,
        idempotency_key=key,
        create_request=request,
        **kwargs,
    )
    assert basis == ("recorded_key" if key else None)
    return run_id, replayed


def test_keyed_create_mints_one_run(db_path: str) -> None:
    run_id, replayed = _create(db_path, "release-1", _request())

    assert replayed is False
    assert dr.cmd_get(run_id, db_path=db_path) is not None


def test_exact_replay_returns_the_original_run(db_path: str) -> None:
    first, _ = _create(db_path, "release-1", _request())
    again, replayed = _create(db_path, "release-1", _request())

    assert (again, replayed) == (first, True)
    assert dr.cmd_next_id(db_path=db_path).endswith("-002")


def test_changed_request_under_the_same_key_refuses(db_path: str) -> None:
    first, _ = _create(db_path, "release-1", _request())
    lineage = "b" * 40

    with pytest.raises(IdempotencyKeyConflict) as refused:
        _create(
            db_path,
            "release-1",
            _request(release_lineage=lineage),
            release_lineage=lineage,
        )

    assert refused.value.run_id == first
    assert "release_lineage" in str(refused.value)
    assert "new --idempotency-key" in str(refused.value)


def test_new_key_for_the_same_candidate_is_a_new_run(db_path: str) -> None:
    first, _ = _create(db_path, "release-1", _request())
    second, replayed = _create(db_path, "release-2", _request())

    assert replayed is False
    assert second != first


def test_unkeyed_creates_stay_independent(db_path: str) -> None:
    first = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    second = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)

    assert first != second


def test_concurrent_replays_share_one_run(db_path: str) -> None:
    results: list[tuple[str, bool]] = []
    errors: list[BaseException] = []
    start = threading.Barrier(4)

    def attempt() -> None:
        start.wait()
        try:
            results.append(_create(db_path, "release-1", _request()))
        except BaseException as exc:  # surfaced below with its traceback
            errors.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len({run_id for run_id, _ in results}) == 1
    assert sorted(replayed for _, replayed in results) == [False, True, True, True]


@pytest.mark.parametrize("environment", [None, "prod"])
def test_merge_only_flow_refuses_before_composition(db_path, environment, monkeypatch):
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_flow_state import MergeOnlyRunRefused
    from yoke_core.domain import deployment_run_create_write as creation

    conn = connect(db_path)
    conn.execute("UPDATE deployment_flows SET target_tier=NULL, target_environment_id=NULL WHERE id=%s", ("flow-main",))
    conn.commit()
    monkeypatch.setattr(creation, "compose_run", lambda *_a, **_k: pytest.fail("merge-only cannot compose"))
    with pytest.raises(MergeOnlyRunRefused) as refused:
        create_run("yoke", "flow-main", db_path=db_path, environment=environment)
    assert refused.value.code == "merge_only_flow_no_release_run"
    assert "merge close-out" in str(refused.value)
    assert conn.execute("SELECT COUNT(*) FROM deployment_runs").fetchone()[0] == 0
    conn.close()
