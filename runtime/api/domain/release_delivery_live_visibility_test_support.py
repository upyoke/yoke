# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain import deployment_run_contained_items as containment_module

from yoke_core.domain.deployment_run_candidate_containment import (
    UNDETERMINED,
    ContainmentVerdict,
)

from yoke_core.domain.deployment_run_contained_items import (
    attest_candidate_containment as attest,
    candidate_containment_basis,
    parse_candidate_containment,
)

from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

from yoke_core.domain.item_merge_receipt_document import record_entry

from yoke_core.domain.json_helper import dumps_compact

from yoke_core.domain.release_delivery_summary import (
    ReleaseCandidates,
    delivery_summary,
    recorded_merge_shas_for_items,
)

FLOW = "yoke-hosted-stage-consumer-bound"

PROD_FLOW = "yoke-hosted-production"

ITEM_ID = 5521

PROJECT_ID = 1

ENVIRONMENT_ID = 7

MERGE = "a" * 40

LINEAGE = "d" * 40


class _LocalAnswer:
    origin = "checkout"
    location = "/repo"

    def __init__(self, contained: bool, *, seen: list[str] | None = None):
        self._contained = contained
        self._seen = seen if seen is not None else []

    def resolve_commit(self, ref):
        return ref

    def contains_commit(self, candidate, commit):
        self._seen.append(commit)
        return self._contained

    def adds_nothing(self, candidate, commit):
        return False


def _open_item(conn) -> None:
    insert_item(
        conn,
        id=ITEM_ID,
        title="waiting on a stage run",
        status="release",
        merged_at="2026-09-20T12:00:00Z",
        project_id=PROJECT_ID,
        deployment_flow=PROD_FLOW,
    )
    record_entry(
        conn,
        item_id=ITEM_ID,
        branch=f"LANE-{ITEM_ID}",
        target="main",
        commit_sha=MERGE,
        merge_sha=MERGE,
    )


def _stage_run(conn, *, status: str = "created") -> None:
    insert_deployment_run(
        conn,
        id="run-stage",
        project_id=PROJECT_ID,
        status=status,
        flow=FLOW,
        target_tier="persistent",
        release_lineage=LINEAGE,
        target_environment_id=ENVIRONMENT_ID,
        current_stage="item-qa",
    )
