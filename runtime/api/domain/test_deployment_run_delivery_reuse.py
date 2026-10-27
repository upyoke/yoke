"""A workflow stage reuses the target's delivery only on an exact served match."""

from __future__ import annotations

import json
from typing import Any

import pytest
from yoke_contracts.timestamps import utc_now

from runtime.api.domain.coordination_claim_test_support import seed_project
from runtime.api.fixtures.backlog_insert_support import ensure_environment_id
from runtime.api.fixtures.hosted_promotion import envelope, payload
from yoke_core.domain.deployment_run_bound_sources import parse_bound_sources
from yoke_core.domain.deployment_run_delivery_reuse import reuse_delivery
from yoke_core.domain.deployment_run_project_sources import run_delivered_sha

PRODUCT_SHA = "a" * 40
CONSUMER_SHA = "b" * 40
CONSUMER_ID = 995
CONSUMER = "reuse-consumer"
FLOW = "reuse-hosted-release"
OTHER_FLOW = "reuse-consumer-delivery"
PRODUCT_PROD, CONSUMER_PROD = 9901, 9902
STAGE = "hosted-release"


def _sources(commit: str, receipts: list | None = None) -> str:
    entry: dict[str, Any] = {
        "project": CONSUMER,
        "project_id": CONSUMER_ID,
        "commit_sha": commit,
    }
    if receipts is not None:
        entry["consumed_by"] = STAGE
        entry["promotion_receipts"] = receipts
    return json.dumps(
        {"schema": 1, "projects": [entry], "inputs": {"consumer_sha": commit}}
    )


def _receipt(**changes: str) -> dict:
    return envelope(
        payload(
            target_environment="prod",
            product_sha=PRODUCT_SHA,
            platform_sha=CONSUMER_SHA,
            **changes,
        )
    )


def _run(conn, run_id, *, status, completed_at, sources, lineage=PRODUCT_SHA,
         project_id=1, flow=FLOW, environment=PRODUCT_PROD) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,created_at,completed_at,bound_sources,target_environment_id,"
        "target_tier) VALUES (%s,%s,%s,%s,%s,'complete',%s,%s,%s,%s,'persistent')",
        (run_id, project_id, flow, lineage, status,
         completed_at or "2026-10-27T12:00:00Z", completed_at,
         sources, environment),
    )
    conn.commit()


@pytest.fixture
def hosted(test_db):
    seed_project(test_db, CONSUMER_ID, CONSUMER)
    for environment, project_id in ((PRODUCT_PROD, 1), (CONSUMER_PROD, CONSUMER_ID)):
        ensure_environment_id(test_db, environment, project_id, ts=utc_now())
        test_db.execute(
            "UPDATE environments SET name='prod' WHERE id=%s", (environment,)
        )
    stages = [
        {"name": "merged", "step_runner": "auto"},
        {
            "name": STAGE,
            "step_runner": "github-actions-workflow",
            "workflow": "platform-release-bridge.yml",
            "input_bindings": {"consumer_sha": {"project": CONSUMER, "branch": "main"}},
        },
        {"name": "warm-up", "step_runner": "warm-up"},
    ]
    for flow, project_id in ((FLOW, 1), (OTHER_FLOW, CONSUMER_ID)):
        test_db.execute(
            "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
            "created_at,status,definition_schema_version) "
            "VALUES (%s,%s,%s,'',%s,'2026-10-27T00:00:00Z','active',2)",
            (flow, project_id, flow, json.dumps(stages)),
        )
    test_db.commit()
    return test_db


def _current(conn, *, lineage=PRODUCT_SHA, commit=CONSUMER_SHA) -> dict:
    _run(conn, "run-current", status="executing", completed_at=None,
         sources=_sources(commit), lineage=lineage)
    result = reuse_delivery(conn, "run-current", STAGE)
    conn.commit()
    return result


def _served(conn, run_id="run-served", **changes) -> None:
    _run(conn, run_id, status="succeeded", completed_at="2026-10-27T10:00:00Z",
         sources=_sources(CONSUMER_SHA, [_receipt(**changes)]))


def _stored(conn) -> dict:
    return parse_bound_sources(
        conn.execute(
            "SELECT bound_sources FROM deployment_runs WHERE id='run-current'"
        ).fetchone()[0]
    )


def test_exact_served_match_reuses_and_records_delivered_identity(hosted):
    _served(hosted)
    assert _current(hosted) == {"reused_run_id": "run-served", "reason": ""}
    stored = _stored(hosted)
    entry = stored["projects"][0]
    assert entry["consumed_by"] == STAGE
    assert entry["promotion_receipts"] == [_receipt()]
    assert stored["delivery_reuse"][STAGE]["run_id"] == "run-served"
    assert run_delivered_sha(hosted, "run-current", CONSUMER_ID) == CONSUMER_SHA
    # A lost answer asked again names the same run and writes nothing new.
    assert reuse_delivery(hosted, "run-current", STAGE)["reused_run_id"] == "run-served"
    assert _stored(hosted) == stored


def test_changed_product_dispatches(hosted):
    _served(hosted)
    result = _current(hosted, lineage="c" * 40)
    assert result["reused_run_id"] == ""
    assert "product_sha" in result["reason"]
    assert "delivery_reuse" not in _stored(hosted)


def test_changed_consumer_dispatches(hosted):
    _served(hosted)
    result = _current(hosted, commit="d" * 40)
    assert result["reused_run_id"] == ""
    assert "platform_sha" in result["reason"]
    assert "consumed_by" not in _stored(hosted)["projects"][0]


def test_newer_other_flow_delivery_dispatches(hosted):
    _served(hosted)
    _run(hosted, "run-consumer", status="succeeded",
         completed_at="2026-10-27T11:00:00Z", sources=_sources(CONSUMER_SHA),
         lineage=CONSUMER_SHA, project_id=CONSUMER_ID, flow=OTHER_FLOW,
         environment=CONSUMER_PROD)
    result = _current(hosted)
    assert result["reused_run_id"] == ""
    assert "run-consumer" in result["reason"]
    assert "no promotion receipt" in result["reason"]


def test_failed_earlier_run_dispatches(hosted):
    # Its promotion succeeded but a later stage failed, so it proves nothing.
    _run(hosted, "run-failed", status="failed", completed_at="2026-10-27T10:00:00Z",
         sources=_sources(CONSUMER_SHA, [_receipt()]))
    result = _current(hosted)
    assert result["reused_run_id"] == ""
    assert "no succeeded run" in result["reason"]
