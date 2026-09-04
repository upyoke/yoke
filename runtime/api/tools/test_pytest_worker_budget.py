"""The machine-wide pytest worker budget: requests, backoff, grants, arbitration."""

from __future__ import annotations

import time
import uuid

import psycopg
import pytest

from yoke_core.tools import gate_admission, pytest_worker_budget as budget
from yoke_core.tools import watch_pytest


def _scratch_lock_base() -> int:
    return int(uuid.uuid4().int % 1_000_000) + 0x7B000000


def test_requested_workers_reads_explicit_auto_and_absent() -> None:
    assert budget.requested_workers(["-n", "6", "tests/"], {}) == 6
    assert budget.requested_workers(["--numprocesses=3"], {}) == 3
    assert budget.requested_workers(["-n", "0"], {}) == 1
    assert budget.requested_workers(["tests/"], {}) == 1
    assert budget.requested_workers(
        ["-n", "auto"], {budget.PYTEST_XDIST_AUTO_WORKERS_ENV: "4"},
    ) == 4
    assert budget.requested_workers(["-n", "auto"], {}) == budget.core_count()


def test_load_backoff_halves_only_when_the_machine_is_over_its_cores() -> None:
    assert budget.load_backoff(8, load=4.0, cores=8) == (8, None)
    granted, note = budget.load_backoff(8, load=9.5, cores=8)
    assert granted == 4
    assert "load 9.5 exceeds 8 cores" in note
    assert budget.load_backoff(1, load=99.0, cores=8) == (1, None)
    assert budget.load_backoff(3, load=99.0, cores=2)[0] == 1


def test_budget_size_prefers_env_then_config_then_cores(monkeypatch) -> None:
    assert budget.budget_size({budget.BUDGET_ENV: "5"}) == 5
    assert budget.budget_size({budget.BUDGET_ENV: "junk"}) in (
        budget.core_count(),
        budget.budget_size({}),
    )
    assert budget.budget_size({}) >= 1


def test_grant_rewrites_the_worker_count_it_allows() -> None:
    grant = budget.Grant(workers=3, requested=10)
    assert grant.apply(["-n", "auto", "tests/"]) == ["-n", "3", "tests/"]
    assert grant.apply(["--numprocesses=10", "-q"]) == ["-n", "3", "-q"]
    assert grant.apply(["-n", "0", "tests/"]) == ["-n", "0", "tests/"]
    assert grant.apply(["tests/"]) == ["tests/"]
    assert budget.Grant(None, 10).apply(["-n", "auto"]) == ["-n", "auto"]


def test_grant_environment_mirrors_the_held_marker(monkeypatch) -> None:
    monkeypatch.setenv(budget.HELD_ENV, "3")
    assert budget.Grant.environment({"A": "1"}) == {"A": "1", budget.HELD_ENV: "3"}
    monkeypatch.delenv(budget.HELD_ENV)
    assert budget.Grant.environment({"A": "1"}) == {"A": "1"}


def test_descendant_of_a_granted_run_does_not_arbitrate(monkeypatch) -> None:
    monkeypatch.setenv(budget.HELD_ENV, "4")
    monkeypatch.setattr(
        budget, "_acquire", lambda *a, **k: pytest.fail("must not arbitrate"),
    )
    with budget.granted_workers(["-n", "auto"], {}) as grant:
        assert grant.workers is None


def test_take_workers_grants_what_is_free_and_returns_on_session_death() -> None:
    dsn = gate_admission.maintenance_dsn()
    assert dsn is not None
    base = _scratch_lock_base()
    first = psycopg.connect(dsn, autocommit=True)
    second = psycopg.connect(dsn, autocommit=True)
    try:
        assert budget.take_workers(first, 5, 3, base=base) == 3
        assert budget.take_workers(second, 2, 3, base=base) == 0
        first.close()
        for _ in range(100):
            if budget.take_workers(second, 2, 3, base=base) == 2:
                break
            time.sleep(0.1)
        else:
            pytest.fail("workers were not returned by holder session death")
    finally:
        first.close()
        second.close()


def test_partial_grant_is_taken_immediately() -> None:
    dsn = gate_admission.maintenance_dsn()
    assert dsn is not None
    base = _scratch_lock_base()
    holder = psycopg.connect(dsn, autocommit=True)
    contender = psycopg.connect(dsn, autocommit=True)
    try:
        assert budget.take_workers(holder, 2, 4, base=base) == 2
        assert budget.take_workers(contender, 4, 4, base=base) == 2
    finally:
        holder.close()
        contender.close()


def test_granted_workers_rewrites_args_and_publishes_the_marker(monkeypatch) -> None:
    monkeypatch.delenv(budget.HELD_ENV, raising=False)
    monkeypatch.setenv(budget.BUDGET_ENV, "2")
    monkeypatch.setenv(budget.LOCK_BASE_ENV, str(_scratch_lock_base()))
    monkeypatch.setattr(budget, "load_backoff", lambda request, **k: (request, None))
    with budget.granted_workers(["-n", "auto"], {budget.PYTEST_XDIST_AUTO_WORKERS_ENV: "4"}) as grant:
        assert grant.workers == 2
        assert grant.apply(["-n", "auto", "x.py"]) == ["-n", "2", "x.py"]
        assert budget.Grant.environment({})[budget.HELD_ENV] == "2"
    assert budget.HELD_ENV not in __import__("os").environ


def test_disabled_budget_runs_ungoverned(monkeypatch) -> None:
    monkeypatch.delenv(budget.HELD_ENV, raising=False)
    monkeypatch.setenv(budget.BUDGET_ENV, "0")
    with budget.granted_workers(["-n", "auto"], {}) as grant:
        assert grant.workers is None


def test_waiting_announcement_names_holders_and_queue() -> None:
    text = budget.waiting_announcement(18, 31.0, ["lane-a/pid1=10", "lane-b/pid2=8"], 3)
    assert "all 18 worker(s) held by lane-a/pid1=10, lane-b/pid2=8" in text
    assert "2 other queued run(s)" in text
    assert "31s so far" in text


def test_local_postgres_auto_worker_env_reaches_runner(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)
    monkeypatch.setattr(watch_pytest.verification_tree_binding, "evaluate_run", lambda **_: watch_pytest.verification_tree_binding.TreeBindingVerdict())
    monkeypatch.setattr(
        watch_pytest._source_pythonpath,
        "import_origin_refusal",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        watch_pytest._watch_runner,
        "run_watcher",
        lambda **kwargs: captured.update(kwargs) or 0,
    )
    assert watch_pytest.main(["--", "-n", "auto", "runtime/api/tools"]) == 0
    assert captured["env"]["PYTEST_XDIST_AUTO_NUM_WORKERS"] == "10"
    assert "packages/yoke-core/src" in captured["env"]["PYTHONPATH"]
    # Two shapes are correct here, and which one appears is the environment
    # rather than the contract: where a budget cluster is reachable the
    # machine-wide worker budget resolves ``auto`` up front and hands the
    # runner a concrete grant; where it is not, the budget fails open by
    # design and ``auto`` passes through for xdist to expand from the cap
    # above. Either way the cap is what bounds the workers that start.
    argv = captured["argv"]
    assert "-n" in argv
    workers = argv[argv.index("-n") + 1]
    assert workers == "auto" or 1 <= int(workers) <= 10
