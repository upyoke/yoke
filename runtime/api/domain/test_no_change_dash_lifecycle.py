"""A genuine no-change Dash can enter and close its own lifecycle."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.conflict_survey import DURABLE_RECORDED
from yoke_core.domain import conflict_survey_gate
from yoke_core.domain import db_helpers
from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_evidence as merge_evidence
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain.handlers.direct_workflow_conflict_survey_status import (
    handle_conflict_survey_status,
)
from yoke_core.domain.handlers.direct_workflow_execution import (
    handle_dash_survey,
)

LANE_SHA = "1" * 40


@pytest.fixture(autouse=True)
def _item_sections_contract(test_db):
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS item_sections ("
        "item_id INTEGER NOT NULL REFERENCES items(id), "
        "section_name TEXT NOT NULL, content TEXT NOT NULL, "
        "ordering INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(item_id, section_name))"
    )
    test_db.commit()


@contextmanager
def _use_connection(connection):
    yield connection


class _NonClosingConnection:
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        return None


def _request(function: str, item_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="test", session_id="session"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def test_explicit_empty_survey_satisfies_dash_entry_gate(
    test_db,
    monkeypatch,
):
    item_id = 7101
    insert_item(test_db, id=item_id, workflow_id="dash", title="No change")
    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: _use_connection(test_db),
    )

    recorded = handle_dash_survey(
        _request(
            "direct_workflow.dash.survey",
            item_id,
            {"paths": [], "path_sizes": [], "no_changes": True},
        )
    )

    assert recorded.primary_success is True
    assert recorded.result_payload["touch_paths"] == []
    assert recorded.result_payload["no_changes"] is True
    status = handle_conflict_survey_status(
        _request(
            "direct_workflow.conflict_survey.status",
            item_id,
            {},
        )
    )
    assert status.primary_success is True
    assert status.result_payload["durable_state"] == DURABLE_RECORDED
    assert status.result_payload["found"] is True
    assert status.result_payload["clear"] is True
    assert status.result_payload["no_changes"] is True

    monkeypatch.setattr(
        conflict_survey_gate,
        "connect",
        lambda _path: _NonClosingConnection(test_db),
    )
    assert (
        conflict_survey_gate.evaluate(
            item_id=item_id,
            target_status="implementing",
            db_path="unused",
        )
        is None
    )


def test_no_change_merge_records_base_identity_and_closes_dash(
    monkeypatch,
    capsys,
):
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [
            {
                "path": "/repo/.worktrees/ITEM-1",
                "branch": "ITEM-1",
                "state": "active",
            }
        ],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli, "_ensure_usable_cwd", lambda *_a: None)
    monkeypatch.setattr(
        merge_cli.landed,
        "landed_lane",
        lambda **_kw: landed.LandedLane(
            branch="ITEM-1",
            target="main",
            commit_sha=LANE_SHA,
            merge_sha="",
            touched_files=(),
            source="lane branch",
        ),
    )
    monkeypatch.setattr(landed.git, "has_remote", lambda *_a: False)
    receipts = []
    monkeypatch.setattr(
        landed.receipts,
        "record",
        lambda _item, receipt, **_kw: receipts.append(receipt) or "",
    )
    monkeypatch.setattr(
        merge_domain,
        "stamp_merged_at",
        lambda _item_id: None,
    )
    monkeypatch.setattr(
        merge_domain,
        "sync_item_to_github",
        lambda _item_id: None,
    )
    monkeypatch.setattr(terminal.git, "is_landed", lambda *_a: True)
    monkeypatch.setattr(terminal.recovery, "claim_error", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli,
        "cleanup_terminal_item_lanes",
        lambda *_a, **_kw: (),
    )
    calls = []

    def dispatch(*, function_id, payload=None, **_kwargs):
        calls.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(merge_evidence, "call_dispatcher", dispatch)
    monkeypatch.setattr(terminal, "call_dispatcher", dispatch)

    exit_code = merge_cli.run(
        [
            "ITEM-1",
            "--result",
            "No change was required",
            "--verification",
            "Registered case passed",
            "--no-changes",
            "--json",
        ]
    )

    assert exit_code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is True
    assert envelope["status"] == "done"
    assert envelope["already_merged"] is True
    assert envelope["commit_sha"] == LANE_SHA
    assert envelope["merge_sha"] == LANE_SHA
    assert receipts[0].merge_sha == LANE_SHA
    evidence = dict(calls)["direct_workflow.dash.evidence"]
    assert evidence["commit_sha"] == ""
    assert evidence["merge_sha"] == ""
    assert evidence["touched_files"] == []
    assert evidence["no_changes"] is True
