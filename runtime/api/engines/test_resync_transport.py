"""Transport-aware routing regression tests for the resync engine.

The resync engine's control-plane reads and its one epic-task write must
route through the transport-aware ``call_dispatcher`` facade so resync runs
over an https control plane, not only a local Postgres connection. These
tests monkeypatch ``call_dispatcher`` (and fail on any bare
``db_helpers.connect``) and assert:

* the runtime item-status probe relays ``resync.item_lookup``;
* Stage-1 linkage relays ``resync.linkage_roster`` + ``resync.linkage_rows``;
* Stage-2 comparison relays ``resync.compare_prefetch`` and consumes the
  server-resolved ``implies_merge`` flag;
* the drift-title parent lookup relays ``resync.item_lookup``;
* the epic-task repair relays its two reads, performs the GitHub
  ``create_issue`` call BETWEEN the relayed reads and the relayed
  ``resync.epic_task_github_issue_set`` write-back, and stays advisory on a
  failed write.

with no bare ``db_helpers.connect`` on any resync path.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain.github_rest import Issue
from yoke_core.engines import resync_detect_compare as compare
from yoke_core.engines import resync_detect_linkage as linkage
from yoke_core.engines import resync_repair as repair
from yoke_core.engines import resync_repair_epic_task_issue as repair_eti
from yoke_core.engines import resync_runtime as runtime
from yoke_core.engines.resync_detect_models import DriftRecord, PairedItem

_ADAPTER = "yoke_core.api.service_client_structured_api_adapter.call_dispatcher"


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _fail_on_connect(monkeypatch):
    def _boom(*a, **k):
        pytest.fail("must not open a bare db_helpers.connect on a resync path")

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", _boom)


def test_query_item_status_relays_item_lookup(monkeypatch):
    seen = []

    def fake(**kwargs):
        seen.append(kwargs["function_id"])
        return _resp(kwargs["function_id"], {"found": True, "status": "done"})

    monkeypatch.setattr(_ADAPTER, fake)
    _fail_on_connect(monkeypatch)
    assert runtime._query_item_status("42") == "done"
    assert seen == ["resync.item_lookup"]


def test_query_item_status_missing_is_none(monkeypatch):
    monkeypatch.setattr(
        _ADAPTER,
        lambda **kw: _resp(kw["function_id"], {"found": False}),
    )
    _fail_on_connect(monkeypatch)
    assert runtime._query_item_status("999") is None


def test_stage1_linkage_relays_roster_and_rows(monkeypatch):
    seen = []

    def fake(**kwargs):
        fid = kwargs["function_id"]
        seen.append(fid)
        if fid == "resync.linkage_roster":
            return _resp(fid, {"fetch_projects": ["yoke"], "sync_disabled": {}})
        if fid == "resync.linkage_rows":
            # (id, github_issue, project_slug, public_item_prefix,
            #  project_sequence) — the last two render the public ref.
            return _resp(fid, {
                "backlog_rows": [[7, "#5", "yoke", "YOK", 1]],
                "task_rows": [],
            })
        return _resp(fid, {})

    monkeypatch.setattr(_ADAPTER, fake)
    _fail_on_connect(monkeypatch)

    def fetch_fn(_projects):
        return {"yoke": {5: {"title": "[YOK-1] a", "state": "OPEN"}}}

    paired, local_orphans, gh_orphans, gh_by_project = linkage.stage1_linkage(
        "", "", fetch_fn=fetch_fn, project="",
    )
    assert seen == ["resync.linkage_roster", "resync.linkage_rows"]
    # Linked to GitHub #5 -> paired, not a local orphan. The display ref
    # renders from prefix+sequence while identity stays the internal id,
    # so a diverged sequence (7 vs 1) still pairs on the id.
    assert [p.ref for p in paired] == ["YOK-1"]
    assert [p.item_id for p in paired] == [7]
    assert local_orphans == []


def test_stage2_compare_relays_prefetch_and_uses_implies_merge(monkeypatch):
    seen = []

    def fake(**kwargs):
        fid = kwargs["function_id"]
        seen.append(fid)
        return _resp(fid, {
            "items": [{
                "id": 1, "title": "A", "status": "done", "priority": "",
                "workflow_id": "", "source_label": "", "owner_label": "",
                "frozen": 0, "blocked": 0, "body": "", "implies_merge": True,
            }],
            "epic_tasks": [],
        })

    monkeypatch.setattr(_ADAPTER, fake)
    _fail_on_connect(monkeypatch)

    paired = [PairedItem(
        "YOK-1", "/tmp/001.md", 5, "backlog", "yoke", "", item_id=1,
    )]
    gh_by_project = {"yoke": {5: {"title": "A", "state": "OPEN", "labels": []}}}
    drifts = compare.stage2_compare(paired, gh_by_project, {}, "")
    assert seen == ["resync.compare_prefetch"]
    # implies_merge=True -> the engine expects the issue CLOSED; #5 is OPEN,
    # so a state drift is recorded from the server-resolved flag.
    assert any(d.field == "state" and d.github == "OPEN" for d in drifts)


def test_repair_drift_title_relays_parent_lookup(monkeypatch):
    seen = []

    def fake(**kwargs):
        seen.append(kwargs["function_id"])
        return _resp(
            kwargs["function_id"],
            {"found": True, "id": 1246, "ref": "YOK-1246"},
        )

    monkeypatch.setattr(_ADAPTER, fake)
    _fail_on_connect(monkeypatch)

    drift = DriftRecord(
        "1246/task-001", "title", "Task one fixed", "Wrong",
        epic_id="1246", task_num=1,
    )
    paired = [PairedItem(
        "1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", "",
        epic_id="1246", task_num=1,
    )]
    edits = []
    monkeypatch.setattr(
        repair, "_edit_issue_title_via_rest",
        lambda **kw: edits.append(kw) or True,
    )
    assert repair._repair_drift(
        drift, paired, "",
        call_domain_sync_fn=lambda *a, **k: True,
        is_dry_run_fn=lambda: False,
        query_item_status_fn=lambda _n: "done",
    ) is True
    assert seen == ["resync.item_lookup"]
    assert edits[0]["title"] == "[YOK-1246] 001 Task one fixed"


class TestEpicTaskRepairOrdering:
    def _run(self, monkeypatch, *, status="implementing"):
        events = []

        def fake(**kwargs):
            fid = kwargs["function_id"]
            events.append(("dispatch", fid))
            if fid == "resync.epic_task_repair_read":
                return _resp(fid, {
                    "parent_id": 1246, "parent_ref": "YOK-1246",
                    "task_found": True,
                    "title": "Task one", "status": status,
                })
            if fid == "resync.epic_task_body":
                return _resp(fid, {"body": "task body"})
            if fid == "resync.epic_task_github_issue_set":
                return _resp(fid, {"updated": True})
            return _resp(fid, {})

        monkeypatch.setattr(_ADAPTER, fake)
        _fail_on_connect(monkeypatch)

        def fake_create(**kwargs):
            events.append(("github", "create_issue"))
            return Issue(number=321, title="t", state="OPEN")

        def fake_set_state(**kwargs):
            events.append(("github", "set_issue_state"))
            return Issue(number=321, title="t", state="CLOSED")

        monkeypatch.setattr(repair_eti.github_rest, "create_issue", fake_create)
        monkeypatch.setattr(
            repair_eti.github_rest, "set_issue_state", fake_set_state
        )
        outcome = repair_eti.repair_local_orphan_epic_task_typed(
            "1246", 1, "yoke", "", is_dry_run_fn=lambda: False,
        )
        return outcome, events

    def test_github_create_sits_between_relayed_reads_and_write(self, monkeypatch):
        outcome, events = self._run(monkeypatch)
        assert outcome.success is True

        create_idx = events.index(("github", "create_issue"))
        write_idx = events.index(
            ("dispatch", "resync.epic_task_github_issue_set")
        )
        read_idxs = [
            i for i, e in enumerate(events)
            if e == ("dispatch", "resync.epic_task_repair_read")
            or e == ("dispatch", "resync.epic_task_body")
        ]
        # Both relayed reads precede the GitHub create; the relayed write-back
        # follows it. The GitHub call between them touches no Yoke DB.
        assert read_idxs, "expected relayed reads before the GitHub create"
        assert max(read_idxs) < create_idx < write_idx

    def test_terminal_status_closes_issue_after_write(self, monkeypatch):
        outcome, events = self._run(monkeypatch, status="done")
        assert outcome.success is True
        write_idx = events.index(
            ("dispatch", "resync.epic_task_github_issue_set")
        )
        close_idx = events.index(("github", "set_issue_state"))
        assert write_idx < close_idx

    def test_write_failure_is_advisory(self, monkeypatch):
        def fake(**kwargs):
            fid = kwargs["function_id"]
            if fid == "resync.epic_task_repair_read":
                return _resp(fid, {
                    "parent_id": 1246, "parent_ref": "YOK-1246",
                    "task_found": True,
                    "title": "Task one", "status": "implementing",
                })
            if fid == "resync.epic_task_body":
                return _resp(fid, {"body": "b"})
            if fid == "resync.epic_task_github_issue_set":
                return _resp(fid, success=False)
            return _resp(fid, {})

        monkeypatch.setattr(_ADAPTER, fake)
        _fail_on_connect(monkeypatch)
        monkeypatch.setattr(
            repair_eti.github_rest, "create_issue",
            lambda **kw: Issue(number=321, title="t", state="OPEN"),
        )
        # A failed write-back is advisory: the repair still succeeds.
        outcome = repair_eti.repair_local_orphan_epic_task_typed(
            "1246", 1, "yoke", "", is_dry_run_fn=lambda: False,
        )
        assert outcome.success is True
