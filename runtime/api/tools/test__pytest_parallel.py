"""Tests for the default-parallel pytest invocation contract."""

from __future__ import annotations

import pytest

from yoke_core.tools import _pytest_parallel
from yoke_core.tools._pytest_parallel import (
    DEFAULT_PARALLEL_WORKERS,
    DEFAULT_LOCAL_POSTGRES_AUTO_WORKERS,
    DEFAULT_RAM_THRESHOLD_MB,
    LOW_CAPACITY_PARALLEL_WORKERS,
    NO_PARALLEL_FLAG,
    PYTEST_XDIST_AUTO_WORKERS_ENV,
    apply_postgres_xdist_auto_env,
    apply_parallel_default,
    choose_default_workers,
    has_explicit_workers,
    split_no_parallel,
    uses_xdist_auto_workers,
)


@pytest.fixture
def pin_high_capacity(monkeypatch):
    """Force ``choose_default_workers`` to return the high-capacity value.

    Many existing tests assert the literal ``"auto"`` injection. Without
    pinning, the RAM-aware cliff makes those tests environment-dependent.
    """
    monkeypatch.setenv("YOKE_PYTEST_WORKERS", DEFAULT_PARALLEL_WORKERS)


class TestHasExplicitWorkers:
    def test_returns_false_for_empty(self):
        assert has_explicit_workers([]) is False

    def test_returns_false_when_no_n_flag(self):
        assert has_explicit_workers(["runtime/api/", "-q"]) is False

    def test_returns_true_for_short_form(self):
        assert has_explicit_workers(["-n", "4"]) is True

    def test_returns_true_for_long_form(self):
        assert has_explicit_workers(["--numprocesses", "4"]) is True

    def test_returns_true_for_short_equals_form(self):
        assert has_explicit_workers(["-n=4"]) is True

    def test_returns_true_for_long_equals_form(self):
        assert has_explicit_workers(["--numprocesses=4"]) is True


class TestUsesXdistAutoWorkers:
    @pytest.mark.parametrize(
        "args",
        [
            ["-n", "auto", "runtime/api/"],
            ["--numprocesses", "auto", "runtime/api/"],
            ["-n=auto", "runtime/api/"],
            ["--numprocesses=auto", "runtime/api/"],
        ],
    )
    def test_detects_auto_forms(self, args):
        assert uses_xdist_auto_workers(args) is True

    @pytest.mark.parametrize(
        "args",
        [
            ["runtime/api/"],
            ["-n", "10", "runtime/api/"],
            ["--numprocesses=2", "runtime/api/"],
            ["-n"],
        ],
    )
    def test_ignores_non_auto_forms(self, args):
        assert uses_xdist_auto_workers(args) is False


class TestApplyPostgresXdistAutoEnv:
    def test_sets_local_postgres_auto_worker_env(self):
        env = apply_postgres_xdist_auto_env(
            ["-n", "auto", "runtime/api/"],
            {},
        )
        assert env[PYTEST_XDIST_AUTO_WORKERS_ENV] == (
            DEFAULT_LOCAL_POSTGRES_AUTO_WORKERS
        )

    def test_accepts_pg_dsn_as_postgres_signal(self):
        env = apply_postgres_xdist_auto_env(
            ["--numprocesses=auto"],
            {"YOKE_PG_DSN": "host=/tmp/sock user=yoketest dbname=postgres"},
        )
        assert env[PYTEST_XDIST_AUTO_WORKERS_ENV] == (
            DEFAULT_LOCAL_POSTGRES_AUTO_WORKERS
        )

    def test_prepares_matching_local_pg_testcluster(self, monkeypatch):
        from yoke_core.tools import pg_testcluster

        calls = []
        dsn = "host=/tmp/yoke-pgtest-cluster/sock user=yoketest dbname=postgres"
        monkeypatch.setattr(pg_testcluster, "dsn", lambda: dsn)
        monkeypatch.setattr(
            pg_testcluster,
            "prepare_for_pytest",
            lambda: calls.append("prepare") or 0,
        )

        apply_postgres_xdist_auto_env(["-n", "auto"], {"YOKE_PG_DSN": dsn})

        assert calls == ["prepare"]

    def test_prepares_cluster_root_from_pytest_env(self, monkeypatch):
        from yoke_core.tools import pg_testcluster

        calls = []
        root = "/tmp/custom-yoke-pgtest-cluster"
        dsn = f"host={root}/sock user=yoketest dbname=postgres"

        def fake_dsn():
            assert _pytest_parallel.os.environ["YOKE_PG_CLUSTER_ROOT"] == root
            return dsn

        monkeypatch.delenv("YOKE_PG_CLUSTER_ROOT", raising=False)
        monkeypatch.setattr(pg_testcluster, "dsn", fake_dsn)
        monkeypatch.setattr(
            pg_testcluster,
            "prepare_for_pytest",
            lambda: calls.append("prepare") or 0,
        )

        apply_postgres_xdist_auto_env(
            ["-n", "auto"],
            {
                "YOKE_PG_CLUSTER_ROOT": root,
                "YOKE_PG_DSN": dsn,
            },
        )

        assert calls == ["prepare"]
        assert "YOKE_PG_CLUSTER_ROOT" not in _pytest_parallel.os.environ

    def test_operator_auto_worker_override_wins(self):
        env = apply_postgres_xdist_auto_env(
            ["-n", "auto"],
            {
                "YOKE_PG_PYTEST_AUTO_WORKERS": "14",
            },
        )
        assert env[PYTEST_XDIST_AUTO_WORKERS_ENV] == "14"

    def test_preserves_existing_xdist_auto_env(self):
        env = apply_postgres_xdist_auto_env(
            ["-n", "auto"],
            {
                PYTEST_XDIST_AUTO_WORKERS_ENV: "8",
            },
        )
        assert env[PYTEST_XDIST_AUTO_WORKERS_ENV] == "8"

    def test_skips_ci_so_remote_auto_stays_cpu_based(self):
        env = apply_postgres_xdist_auto_env(
            ["-n", "auto"],
            {"CI": "true"},
        )
        assert PYTEST_XDIST_AUTO_WORKERS_ENV not in env

    def test_defaults_local_auto_to_postgres_worker_cap_without_backend_env(self):
        env = apply_postgres_xdist_auto_env(["-n", "auto"], {})
        assert env[PYTEST_XDIST_AUTO_WORKERS_ENV] == (
            DEFAULT_LOCAL_POSTGRES_AUTO_WORKERS
        )

    def test_skips_explicit_numeric_workers(self):
        env = apply_postgres_xdist_auto_env(
            ["-n", "10"],
            {},
        )
        assert PYTEST_XDIST_AUTO_WORKERS_ENV not in env


class TestSplitNoParallel:
    def test_no_flag_returns_unchanged(self):
        found, cleaned = split_no_parallel(["runtime/api/", "-q"])
        assert found is False
        assert cleaned == ["runtime/api/", "-q"]

    def test_strips_flag(self):
        found, cleaned = split_no_parallel(["runtime/api/", NO_PARALLEL_FLAG, "-q"])
        assert found is True
        assert cleaned == ["runtime/api/", "-q"]

    def test_strips_multiple_occurrences(self):
        found, cleaned = split_no_parallel([NO_PARALLEL_FLAG, "-q", NO_PARALLEL_FLAG])
        assert found is True
        assert cleaned == ["-q"]


class TestApplyParallelDefault:
    def test_injects_n_auto_when_absent(self, pin_high_capacity):
        result = apply_parallel_default(["runtime/api/", "-q"])
        assert result == ["-n", DEFAULT_PARALLEL_WORKERS, "runtime/api/", "-q"]

    def test_skips_injection_on_no_parallel(self):
        result = apply_parallel_default(["runtime/api/"], no_parallel=True)
        assert result == ["runtime/api/"]

    def test_respects_explicit_workers(self):
        result = apply_parallel_default(["-n", "4", "runtime/api/"])
        assert result == ["-n", "4", "runtime/api/"]

    def test_respects_long_form_workers(self):
        result = apply_parallel_default(["--numprocesses=2", "runtime/api/"])
        assert result == ["--numprocesses=2", "runtime/api/"]

    def test_empty_args_still_injects(self, pin_high_capacity):
        result = apply_parallel_default([])
        assert result == ["-n", DEFAULT_PARALLEL_WORKERS]


class TestChooseDefaultWorkers:
    def test_env_override_wins_absolutely(self, monkeypatch):
        monkeypatch.setenv("YOKE_PYTEST_WORKERS", "7")
        # Even if the reader said the box was scarce, override stands.
        monkeypatch.setattr(_pytest_parallel, "_read_free_ram_mb", lambda: 100)
        assert choose_default_workers() == "7"

    def test_picks_default_when_ram_above_threshold(self, monkeypatch):
        monkeypatch.delenv("YOKE_PYTEST_WORKERS", raising=False)
        monkeypatch.delenv("YOKE_PYTEST_RAM_THRESHOLD_MB", raising=False)
        monkeypatch.setattr(
            _pytest_parallel,
            "_read_free_ram_mb",
            lambda: DEFAULT_RAM_THRESHOLD_MB + 1,
        )
        assert choose_default_workers() == DEFAULT_PARALLEL_WORKERS

    def test_picks_low_when_ram_below_threshold(self, monkeypatch, capsys):
        monkeypatch.delenv("YOKE_PYTEST_WORKERS", raising=False)
        monkeypatch.delenv("YOKE_PYTEST_RAM_THRESHOLD_MB", raising=False)
        monkeypatch.setattr(_pytest_parallel, "_read_free_ram_mb", lambda: 500)
        assert choose_default_workers() == LOW_CAPACITY_PARALLEL_WORKERS
        captured = capsys.readouterr()
        assert "free RAM 500 MB" in captured.err
        assert f"threshold {DEFAULT_RAM_THRESHOLD_MB} MB" in captured.err

    def test_falls_back_to_default_when_reader_returns_none(self, monkeypatch):
        monkeypatch.delenv("YOKE_PYTEST_WORKERS", raising=False)
        monkeypatch.setattr(_pytest_parallel, "_read_free_ram_mb", lambda: None)
        assert choose_default_workers() == DEFAULT_PARALLEL_WORKERS

    def test_threshold_env_override(self, monkeypatch):
        monkeypatch.delenv("YOKE_PYTEST_WORKERS", raising=False)
        monkeypatch.setenv("YOKE_PYTEST_RAM_THRESHOLD_MB", "1024")
        monkeypatch.setattr(_pytest_parallel, "_read_free_ram_mb", lambda: 2000)
        assert choose_default_workers() == DEFAULT_PARALLEL_WORKERS

    def test_bogus_threshold_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("YOKE_PYTEST_WORKERS", raising=False)
        monkeypatch.setenv("YOKE_PYTEST_RAM_THRESHOLD_MB", "not-a-number")
        monkeypatch.setattr(
            _pytest_parallel,
            "_read_free_ram_mb",
            lambda: DEFAULT_RAM_THRESHOLD_MB + 100,
        )
        assert choose_default_workers() == DEFAULT_PARALLEL_WORKERS
