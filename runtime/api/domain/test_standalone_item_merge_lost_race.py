"""A close-out that loses its terminal transition to a finished one.

Two watchers following one pull request both enter close-out. The first
records evidence, moves the item to ``done``, and releases the work claim.
The second records evidence and is then refused the transition, because the
claim it held going in is gone. That refusal is not a failed landing: the
item is terminal with its merge identity recorded, so the losing run reports
the completed landing under its own name and repeats no re-acquire hint,
which would otherwise re-claim and re-transition a terminal item.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as sim_cli
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.dash_execution import record_dash_evidence

CLAIM_REFUSAL = (
    "no active claim by session 'session-1' on item ITEM-1; acquire one "
    'first: yoke claims work acquire --item ITEM-1 --reason "<intent>"'
)
RECORD = {
    "commit_sha": "1" * 40,
    "merge_sha": "2" * 40,
    "touched_files": ["feature.txt"],
    "recorded_at": "2026-09-03T18:27:48Z",
    "recorded_by_session_id": "session-1",
    "actor_id": "2",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@test.com")
    _git(root, "config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    _git(root, "add", "base.txt")
    _git(root, "commit", "-m", "base")
    _git(root, "checkout", "-b", "ITEM-1")
    (root / "feature.txt").write_text("feature\n")
    _git(root, "add", "feature.txt")
    _git(root, "commit", "-m", "feature")
    _git(root, "checkout", "main")
    return root


def _close_out_racing(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A merge whose terminal transition is refused for the released claim."""
    monkeypatch.setattr(receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(receipts, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(
        sim_cli,
        "_resolve_item",
        lambda ref, project: (
            {
                "id": 7,
                "public_ref": "ITEM-1",
                "status": "reviewing-implementation",
                "workflow": {"id": "dash"},
                "worktrees": [{"commit_sha": _git(repo, "rev-parse", "ITEM-1")}],
            },
            "",
        ),
    )
    monkeypatch.setattr(sim_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        sim_cli,
        "_resolve_checkout",
        lambda item, target: (repo, "main"),
    )
    monkeypatch.setattr(sim_cli.evidence, "record", lambda **_k: "")
    monkeypatch.setattr(
        sim_cli.close_out,
        "transition_to_done",
        lambda **_k: CLAIM_REFUSAL,
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda item_id: None)
    monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id: None)
    monkeypatch.setattr(sim, "_run_merge_engine", lambda **_k: (0, ""))


def _run_close_out(capsys: pytest.CaptureFixture) -> tuple[int, str]:
    exit_code = sim_cli.run(
        ["ITEM-1", "--result", "landed", "--verification", "suite green"],
    )
    return exit_code, capsys.readouterr().out


def test_a_transition_lost_to_a_finished_close_out_is_the_landing(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    _close_out_racing(repo, monkeypatch)
    monkeypatch.setattr(
        evidence,
        "recorded_landing",
        lambda item_id: {**RECORD, "merged_at": "2026-09-03T18:27:22Z"},
    )
    monkeypatch.setattr(
        sim_cli,
        "cleanup_terminal_item_lanes",
        lambda *_a, **_k: pytest.fail("the finished close-out owns cleanup"),
    )

    exit_code, out = _run_close_out(capsys)

    assert exit_code == 0
    envelope = json.loads(out)
    assert envelope["ok"] is True
    assert envelope["result"] == evidence.LANDING_ALREADY_RECORDED
    assert envelope["status"] == "done"
    assert envelope["merge_sha"] == "2" * 40
    assert envelope["recorded_by_session_id"] == "session-1"
    assert "session session-1" in envelope["warnings"][0]
    assert "claims work acquire" not in out


def test_a_missing_claim_on_an_unfinished_item_still_refuses_with_the_hint(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    _close_out_racing(repo, monkeypatch)
    monkeypatch.setattr(evidence, "recorded_landing", lambda item_id: None)

    exit_code, out = _run_close_out(capsys)

    assert exit_code == 1
    envelope = json.loads(out)
    assert envelope["ok"] is False
    assert envelope["evidence_recorded"] is True
    assert "claims work acquire --item ITEM-1" in envelope["error"]
    assert "result" not in envelope


def _dispatch(answers: dict[str, object]):
    def dispatch(*, function_id, payload=None, **_kw):
        answer = answers[function_id]
        return SimpleNamespace(success=True, result=answer, error=None)

    return dispatch


def _answers(*, status="done", merged_at="2026-09-03T18:27:22Z", record=None):
    return {
        "items.detail.get": {"item": {"status": status}},
        "items.get.run": {"fields": {"merged_at": merged_at}},
        "items.section.get": {
            "found": record is not None,
            "content": json.dumps(record) if record is not None else "",
        },
    }


def test_recorded_landing_needs_all_three_facts(monkeypatch) -> None:
    for answers in (
        _answers(status="reviewing-implementation", record=RECORD),
        _answers(merged_at="", record=RECORD),
        _answers(record=None),
        _answers(record={**RECORD, "commit_sha": "", "merge_sha": ""}),
    ):
        monkeypatch.setattr(evidence, "call_dispatcher", _dispatch(answers))
        assert evidence.recorded_landing(7) is None

    monkeypatch.setattr(evidence, "call_dispatcher", _dispatch(_answers(record=RECORD)))
    landing = evidence.recorded_landing(7)
    assert landing is not None
    assert landing["merged_at"] == "2026-09-03T18:27:22Z"
    assert landing["merge_sha"] == "2" * 40


def test_a_record_without_a_session_names_its_actor(monkeypatch) -> None:
    record = {**RECORD, "recorded_by_session_id": ""}
    monkeypatch.setattr(evidence, "call_dispatcher", _dispatch(_answers(record=record)))

    envelope = evidence.recorded_landing_envelope(
        7, public_ref="ITEM-1", branch="ITEM-1"
    )

    assert envelope is not None
    assert envelope["recorded_by_session_id"] == ""
    assert "actor 2" in envelope["warnings"][0]


def test_the_evidence_record_names_the_session_that_wrote_it(test_db) -> None:
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS item_sections ("
        "item_id INTEGER NOT NULL REFERENCES items(id), "
        "section_name TEXT NOT NULL, content TEXT NOT NULL, "
        "ordering INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(item_id, section_name))"
    )
    test_db.commit()
    insert_item(
        test_db,
        id=2144,
        workflow_id="dash",
        status="reviewing-implementation",
    )

    payload = record_dash_evidence(
        test_db,
        item_id=2144,
        result_summary="Landed.",
        verification_summary="Focused regression passed.",
        verification_status="passed",
        commit_sha="a" * 40,
        merge_sha="b" * 40,
        touched_files=["src/close_out.py"],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="a" * 40,
        session_id="session-1",
    )

    assert payload["recorded_by_session_id"] == "session-1"
