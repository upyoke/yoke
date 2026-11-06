# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import importlib

from datetime import timedelta

from types import SimpleNamespace

import pytest

from runtime.api.fixtures.native_instant_database import blank_database

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant

from yoke_core.domain import deployment_run_carried_work_sources as sources

from yoke_core.domain.deployment_flow_succession import succession_chains

STAMP = parse_instant("2026-10-10T23:30:00.123456Z")

DRIVER_STAMP = parse_instant("2026-10-10T23:07:54.695930Z")

history = importlib.import_module(
    "yoke_core.domain.migrations.0070_native_domain_instants"
)


@pytest.fixture
def clocks():
    with blank_database() as conn:
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        conn.execute("SET LOCAL DateStyle = 'ISO, MDY'")
        conn.execute("CREATE TABLE projects (id integer PRIMARY KEY, slug text)")
        conn.execute("INSERT INTO projects VALUES (1,'project')")
        conn.execute(
            "CREATE TABLE items (id integer PRIMARY KEY, project_id integer, "
            "merged_at text, merge_queue_landed_at text, resolution_ref text)"
        )
        conn.execute(
            "CREATE TABLE item_worktrees (item_id integer, branch text, commit_sha text)"
        )
        conn.execute(
            "CREATE TABLE deployment_flows (id text PRIMARY KEY, project_id integer, "
            "status text, supersedes_flow_id text, created_at text, "
            "target_environment_id integer, target_tier text)"
        )
        conn.execute(
            "CREATE TABLE deployment_runs (id text PRIMARY KEY, project_id integer, "
            "flow text, release_lineage text, status text, created_at text)"
        )
        for item_id, stamp in (
            (1, format_instant(STAMP)),
            (2, "2026-03-09 02:32:26"),
            (3, "2026-07-30 15:00:27.569899+00"),
        ):
            conn.execute(
                "INSERT INTO items VALUES (%s,1,%s,NULL,NULL)", (item_id, stamp)
            )
        for flow_id, status, predecessor, stamp in (
            ("root", "disabled", None, "2026-03-08 22:42:21"),
            ("successor", "active", "root", format_instant(STAMP)),
            ("unrelated", "active", None, "2026-03-08 22:42:21"),
            ("unrelated-offset", "active", None, "2026-07-30 15:00:27.569899+00"),
        ):
            conn.execute(
                "INSERT INTO deployment_flows VALUES (%s,1,%s,%s,%s,1,'production')",
                (flow_id, status, predecessor, stamp),
            )
        # Aware datetime parameters reproduce the candidate driver's write
        # into an old TEXT column, including PostgreSQL's short +00 offset.
        conn.execute(
            "INSERT INTO deployment_runs VALUES ('run-clock-filter',1,'successor',%s,"
            "'created',%s)",
            ("a" * 40, DRIVER_STAMP),
        )
        yield conn
