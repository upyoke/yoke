# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import inspect

import json

from typing import Any

import pytest

from runtime.api.domain.deployment_membership_round_trips_test_support import (
    _admit_all,
    _created_run,
    _members,
    _statements,
)

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan

from yoke_core.domain import deployment_run_carried_membership as carried_membership

from yoke_core.domain import deployment_run_start

from yoke_core.domain.deployment_run_bound_sources import record_bound_sources

from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members

from yoke_core.domain.deployment_run_unheld_candidates import (
    CandidateCustody,
    CustodyResolution,
)

from yoke_core.domain.schema_read_scope import composition_reads

SMALL, LARGE = 3, 30

_LOCK = "SELECT status FROM deployment_runs WHERE id=%s FOR UPDATE"

_MEMBER_READERS = frozenset(
    {
        "read_pinned_items",
        "read_snapshot_inputs",
        "outstanding_post_deploy_requirement_sets",
        "item_completion_flow_facts",
        "needed_member_ids",
        "supplemental_item_ids",
        "carried_membership_refusal",
        "open_landing_refusals",
    }
)


class _Recorder:
    """Forward to ``inner``, keeping each statement's reader in order."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.log: list[tuple[str, str]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def execute(self, sql: str, params: Any = ()) -> Any:
        frame = inspect.currentframe().f_back
        while frame and frame.f_globals.get("__name__", "").endswith(
            ("db_helpers", "db_backend")
        ):
            frame = frame.f_back
        reader = frame.f_code.co_name if frame else "unknown"
        self.log.append((reader, " ".join(str(sql).split())))
        return self._inner.execute(sql, params)

    def after_lock(self) -> list[str]:
        index = next(i for i, (_, sql) in enumerate(self.log) if sql == _LOCK)
        return [reader for reader, _ in self.log[index:]]

    def before_lock(self) -> list[str]:
        index = next(i for i, (_, sql) in enumerate(self.log) if sql == _LOCK)
        return [reader for reader, _ in self.log[:index]]


def _known_carried(item_ids: list[int]) -> dict[str, Any]:
    return {
        "schema": 1,
        "derivation": {"contents_known": True, "reason": "test-fixture"},
        "items": [{"item_id": item_id} for item_id in item_ids],
        "commits": [],
        "bound_projects": [],
    }


def _land_before_the_lock(monkeypatch, module: Any, name: str, change) -> None:
    """Commit-visible *change* lands after the unlocked reads, before the lock."""
    real = getattr(module, name)

    def racing(conn, *args, **kwargs):
        change(conn)
        return real(conn, *args, **kwargs)

    monkeypatch.setattr(module, name, racing)
