"""Frozen release QA snapshots name every QA host a test machine, repeatably."""

from __future__ import annotations

import importlib
import json

import pytest

from runtime.api.domain import test_qa_member_machine_partitions as support
from yoke_core.domain.qa_deployment_case_content_refresh import (
    plan_case_content_digest,
)
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.qa_plan_management import QaPlanError

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0091_qa_frozen_snapshot_test_machine_keys"
)
SNAPSHOTS = (
    ("deployment_runs", "id=%s", (support.RUN,)),
    ("deployment_run_items", "run_id=%s AND item_id=%s", (support.RUN, support.MEMBER)),
)


def _retired_config(config):
    renamed = {"test_machine": "machine", "test_machines": "machines"}
    return {renamed.get(key, key): value for key, value in config.items()}


def _retired_entries(entries):
    return [
        {**entry, "method_config": _retired_config(entry["method_config"])}
        for entry in entries
    ]


def _retired_snapshot(snapshot):
    """The snapshot a build before the test machine rename froze."""
    retired = dict(snapshot)
    if "requirements" in retired:
        retired["requirements"] = _retired_entries(retired["requirements"])
    for field in ("plans", "selections"):
        if field in retired:
            retired[field] = [
                {**plan, "cases": _retired_entries(plan["cases"])}
                for plan in retired[field]
            ]
    return retired


def _snapshot(conn, table, where, params):
    return conn.execute(
        f"SELECT requirement_snapshot FROM {table} WHERE {where}", params
    ).fetchone()[0]


def _frozen_cases(snapshot):
    for field in ("plans", "selections"):
        for plan in snapshot.get(field, ()):
            yield from plan["cases"]


def _seed_retired_snapshots(conn, tmp_path, monkeypatch):
    """Freeze a run, then store its snapshots the way builds before 0090 did."""
    support._seed(conn, tmp_path, monkeypatch, inherit=True, run_scope=True)
    current = {}
    for table, where, params in SNAPSHOTS:
        raw = _snapshot(conn, table, where, params)
        assert '"test_machine"' in raw and '"test_machines"' in raw, table
        current[table] = raw
        conn.execute(
            f"UPDATE {table} SET requirement_snapshot=%s WHERE {where}",
            (canonical(_retired_snapshot(json.loads(raw))), *params),
        )
    return current


def test_entry_restores_each_frozen_snapshot_byte_for_byte(
    test_db, tmp_path, monkeypatch
):
    current = _seed_retired_snapshots(test_db, tmp_path, monkeypatch)
    retired = json.loads(_snapshot(test_db, *SNAPSHOTS[0]))
    with pytest.raises(QaPlanError, match=r"unknown=\['machine'\]"):
        plan_case_content_digest(test_db, next(_frozen_cases(retired)))

    MIGRATION.apply(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)

    for table, where, params in SNAPSHOTS:
        raw = _snapshot(test_db, table, where, params)
        assert raw == current[table]
        snapshot = json.loads(raw)
        cases = list(_frozen_cases(snapshot))
        assert cases
        for case in cases:
            assert plan_case_content_digest(test_db, case)
        for requirement in snapshot.get("requirements", ()):
            if requirement.get("method_id"):
                assert plan_case_content_digest(
                    test_db, {**requirement, "case_key": requirement["plan_case_key"]}
                )


def test_invariants_name_a_snapshot_the_entry_has_not_folded(
    test_db, tmp_path, monkeypatch
):
    _seed_retired_snapshots(test_db, tmp_path, monkeypatch)

    with pytest.raises(AssertionError, match="deployment_runs.requirement_snapshot"):
        MIGRATION.invariants(test_db)


def test_fold_keeps_a_current_key_and_leaves_unrelated_content_alone():
    snapshot = {
        "schema": 1,
        "selection": {"plan_ids": [1], "requirement_ids": []},
        "requirements": [
            {"method_id": "machine-state-check", "method_config": {"timeout": 5}},
        ],
        "plans": [
            {
                "attachment": {"qa_phase": "post_deploy", "transition_id": "release"},
                "plan": {"id": 1, "slug": "machine-check"},
                "cases": [
                    {
                        "case_key": "machine",
                        "method_config": {"machine": "old-lab", "test_machine": "lab"},
                    }
                ],
            }
        ],
    }

    folded = MIGRATION.fold_snapshot(snapshot)

    assert folded["plans"][0]["cases"][0]["method_config"] == {"test_machine": "lab"}
    assert folded["requirements"] == snapshot["requirements"]
    assert {key: folded[key] for key in ("schema", "selection")} == {
        key: snapshot[key] for key in ("schema", "selection")
    }
    assert MIGRATION.fold_snapshot(folded) == folded
