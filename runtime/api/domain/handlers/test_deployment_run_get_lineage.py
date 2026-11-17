"""Takeover lineage is readable without changing portable snapshots or writes."""

from io import StringIO

import pytest

from runtime.api.domain.handlers.test_deployment_run_get_members import (
    RUN, _get, _live_carried_work, _run_with_removal,
)
from runtime.api.domain.deployment_run_projection_test_support import _snapshot
from yoke_cli.commands.adapters.deployment_run_output import write_run_summary
from yoke_core.domain.deployment_run_projection import normalize_snapshot, snapshot_digest
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

LINEAGE = ("supersedes_run_id", "superseded_by_run_id")


@pytest.mark.parametrize("field", LINEAGE)
def test_lineage_reads_are_read_only(test_db, monkeypatch, field):
    _run_with_removal(test_db)
    _live_carried_work(monkeypatch)
    links = dict(zip(LINEAGE, ("predecessor-run", "successor-run")))
    test_db.execute(
        "UPDATE deployment_runs SET supersedes_run_id=%s, superseded_by_run_id=%s "
        "WHERE id=%s", (*links.values(), RUN),
    )
    test_db.commit()
    single = _get({"field": field})
    assert single.primary_success, single.error
    assert single.result_payload["value"] == links[field]
    selected = _get({"fields": list(LINEAGE)})
    assert selected.primary_success, selected.error
    assert selected.result_payload["run"] == links
    # Default and CLI --full share this registered read.
    full = _get({})
    assert full.primary_success, full.error
    assert set(LINEAGE) <= set(full.result_payload["fields"])
    assert {key: full.result_payload["run"][key] for key in LINEAGE} == links
    assert "not updatable" in cmd_update(RUN, field, "other-run").lower()
    output = StringIO()
    write_run_summary(full.result_payload, output)
    assert "supersedes: predecessor-run" in output.getvalue()
    assert "superseded by: successor-run" in output.getvalue()


def test_unset_lineage_is_null_and_absent_from_summary(test_db, monkeypatch):
    _run_with_removal(test_db)
    _live_carried_work(monkeypatch)
    outcome = _get({})
    assert outcome.primary_success, outcome.error
    assert all(outcome.result_payload["run"][key] is None for key in LINEAGE)
    output = StringIO()
    write_run_summary(outcome.result_payload, output)
    assert "supersedes:" not in output.getvalue()
    assert "superseded by:" not in output.getvalue()


def test_existing_snapshot_keeps_its_fields_and_digest():
    snapshot = _snapshot()
    assert not set(LINEAGE) & set(RUN_FIELDS)
    normalized = normalize_snapshot(snapshot)
    assert normalize_snapshot(normalized) == normalized
    assert snapshot_digest(snapshot) == snapshot_digest(normalized)
