"""Every landing blocker is found in one pass, and review is entered by the merge."""

from __future__ import annotations

from runtime.api.domain.merge_landing_readiness_test_support import (
    ITEM_SCOPED_QA as ITEM_SCOPED_QA,
    _item as _item,
    _run as _run,
    merge as merge,
)


import json
from types import SimpleNamespace


from yoke_core.domain import merge_landing_readiness as readiness_gate
from yoke_core.domain import merge_review_readiness as review_gate


def test_one_refusal_names_every_blocker_and_the_stage_is_not_one(merge, capsys):
    exit_code = _run()

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "2 landing blockers" in err
    assert "[close-out evidence]" in err
    assert "[post-deploy QA]" in err
    assert "yoke qa post-deploy record-no-obligation --item ITEM-51" in err
    assert "[review stage]" not in err
    assert merge["transitions"] == []
    assert merge["landed"] == 0


def test_the_qa_answer_is_the_only_blocker_once_evidence_is_passed(merge, capsys):
    exit_code = _run("--result", "done", "--verification", "green CI")

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "1 landing blocker." in err
    assert "[post-deploy QA]" in err
    assert merge["transitions"] == []


def test_check_prints_the_same_report_and_changes_nothing(merge, capsys):
    exit_code = _run("--check", "--json")

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False
    assert [b["gate"] for b in report["blockers"]] == [
        "close-out evidence",
        "post-deploy QA",
    ]
    assert any("'reviewing-implementation'" in note for note in report["merge_will"])
    assert merge["transitions"] == []
    assert merge["landed"] == 0


def test_a_ready_item_enters_review_with_the_verification_then_lands(merge):
    merge["item"] = _item(
        qa_requirements=[{"qa_phase": "post_deploy", "qa_kind": "check"}]
    )

    _run("--result", "done", "--verification", "green CI")

    assert merge["transitions"] == [
        ("implementing", "reviewing-implementation", "green CI")
    ]
    assert merge["landed"] == 1


def test_check_on_a_ready_item_exits_zero(merge, capsys):
    merge["item"] = _item(status="reviewing-implementation", completion_flow="")

    assert _run("--check", "--result", "r", "--verification", "v") == 0
    assert "ITEM-51: ready to land." in capsys.readouterr().out
    assert merge["landed"] == 0


def test_uncommitted_lane_files_are_a_blocker(merge, monkeypatch, tmp_path, capsys):
    lane = tmp_path / "lane"
    lane.mkdir()
    merge["item"] = _item(
        completion_flow="",
        worktrees=[{"branch": "ITEM-51", "state": "active", "path": str(lane)}],
    )
    monkeypatch.setattr(
        readiness_gate, "classify_dirty_files", lambda **_k: ([], ["notes.txt"])
    )

    assert _run("--check", "--result", "r", "--verification", "v") == 1
    out = capsys.readouterr().out
    assert "[clean tree]" in out
    assert "notes.txt" in out


def test_check_refuses_new_migration_entries_even_after_review(
    merge,
    monkeypatch,
    tmp_path,
    capsys,
):
    from runtime.api.domain.migration_merge_preflight_test_support import _lane
    from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed

    repo = _lane(tmp_path, "0014_new")
    merge["item"] = _item(
        status="reviewing-implementation",
        completion_flow="",
        worktrees=[{"path": str(repo), "branch": "lane"}],
    )
    monkeypatch.setattr(readiness_gate, "classify_dirty_files", lambda **_k: ([], []))
    served = review_gate.call_dispatcher

    def dispatch(**kwargs):
        function = kwargs["function_id"]
        if function == "projects.capability_settings.get":
            return SimpleNamespace(success=True, result={"settings_json": json.dumps(governed_postgres_test_seed())})
        if function == "items.get.run":
            return SimpleNamespace(success=True, result={"fields": {"db_mutation_profile": {"state": "none"}}})
        return served(**kwargs)

    monkeypatch.setattr(review_gate, "call_dispatcher", dispatch)
    assert _run("--check", "--result", "r", "--verification", "v") == 1
    output = capsys.readouterr().out
    assert "0014_new.py" in output
    assert "yoke db-claim amend" in output
    assert merge["transitions"] == []
    assert merge["landed"] == 0
