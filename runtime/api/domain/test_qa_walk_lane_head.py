"""The partition read records the claimant lane's HEAD before a walk grant leaves it."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.domain import lane_head_client, lane_head_record, qa_lane_head
from yoke_core.domain import qa_plan_partitions_cli as cli

NEW = "b" * 40


def _partitions(sha, *, kind="walk", state="free"):
    return {
        "lane": {"lane_id": 2, "lane_branch": "YOK-1", "lane_path": "/lane", "lane_commit_sha": sha},
        "partitions": [{"key": "p1", "state": state, "kind": kind, "hosts": ["macos"],
                        "cases": [{"case_key": "walk"}], "blocked_by": []}],
    }


@pytest.fixture
def wired(monkeypatch):
    calls = {"reads": [], "lanes": [], "writes": []}
    record = {"id": 2, "path": "/lane", "branch": "YOK-1", "commit_sha": None}

    def read(**kwargs):
        calls["reads"].append(kwargs["payload"])
        return _partitions(NEW if calls["writes"] else None)

    monkeypatch.setattr(cli, "call_plan_function", read)
    monkeypatch.setattr(qa_lane_head, "reconcile_plan_lanes", lambda *a, **k: None)
    monkeypatch.setattr(
        "yoke_contracts.runtime_ports.structured_dispatch.get_structured_dispatch",
        lambda: SimpleNamespace(build_actor=lambda **kw: ActorContext(session_id="claimant")),
    )
    monkeypatch.setattr(
        lane_head_client, "read_item_lanes",
        lambda target, actor: calls["lanes"].append(target.public_ref) or ("yoke", [record]),
    )
    return calls


def test_unstamped_claimant_lane_is_recorded_and_the_grant_reread(monkeypatch, wired, capsys):
    def reconcile(project, lane, *, session_id):
        wired["writes"].append((project, lane["id"], session_id))
        return NEW, ""

    monkeypatch.setattr(qa_lane_head, "reconcile_lane_head", reconcile)
    assert cli.run(["--item", "YOK-1", "--transition", "implemented", "--json"]) == 0
    assert wired["writes"] == [("yoke", 2, "claimant")]
    assert len(wired["reads"]) == 2
    assert json.loads(capsys.readouterr().out)["lane"]["lane_commit_sha"] == NEW


@pytest.mark.parametrize("kind, state", [("lane", "lane"), ("walk", "held"), ("walk", "passed")])
def test_reads_without_a_free_walk_partition_stay_read_only(monkeypatch, wired, kind, state):
    monkeypatch.setattr(cli, "call_plan_function", lambda **kw: _partitions(None, kind=kind, state=state))
    monkeypatch.setattr(qa_lane_head, "reconcile_lane_head", lambda *a, **k: pytest.fail("write"))
    assert cli.run(["--item", "YOK-1", "--transition", "implemented", "--json"]) == 0
    assert wired["lanes"] == []


def test_lane_absent_from_this_host_needs_no_checkout(monkeypatch, wired, tmp_path):
    monkeypatch.setattr(
        lane_head_client, "read_item_lanes",
        lambda target, actor: ("yoke", [{"id": 2, "path": str(tmp_path / "gone"), "commit_sha": None}]),
    )
    monkeypatch.setattr(
        lane_head_record, "record_lane_head", lambda *a, **k: pytest.fail("write")
    )
    assert cli.run(["--item", "YOK-1", "--transition", "implemented", "--json"]) == 0
    assert len(wired["reads"]) == 1


def test_released_or_foreign_lane_is_not_recorded(monkeypatch, wired):
    monkeypatch.setattr(lane_head_client, "read_item_lanes", lambda target, actor: ("yoke", []))
    monkeypatch.setattr(qa_lane_head, "reconcile_lane_head", lambda *a, **k: pytest.fail("write"))
    assert cli.run(["--item", "YOK-1", "--transition", "implemented", "--json"]) == 0
    assert len(wired["reads"]) == 1


def test_recording_failure_refuses_with_its_named_reason(monkeypatch, wired, capsys):
    monkeypatch.setattr(
        qa_lane_head, "reconcile_lane_head",
        lambda *a, **k: ("", "lane_head_branch_mismatch: /lane is on 'other'"),
    )
    assert cli.run(["--item", "YOK-1", "--transition", "implemented", "--json"]) == 2
    assert "lane_head_branch_mismatch" in capsys.readouterr().err
    assert len(wired["reads"]) == 1


def test_real_checkout_head_is_the_head_recorded(monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "YOK-1", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "--allow-empty", "-m", "x"], check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    recorded = []
    monkeypatch.setattr(
        lane_head_record, "record_lane_head",
        lambda project, path, *, expected_head, session_id: recorded.append(expected_head) or "",
    )
    monkeypatch.setattr(
        lane_head_client, "read_item_lanes",
        lambda target, actor: ("yoke", [{"id": 2, "path": str(tmp_path), "branch": "YOK-1"}]),
    )
    assert qa_lane_head.reconcile_walk_lane(
        TargetRef(kind="item", public_ref="YOK-1"), _partitions(None),
        ActorContext(session_id="claimant"),
    )
    assert recorded == [head]
