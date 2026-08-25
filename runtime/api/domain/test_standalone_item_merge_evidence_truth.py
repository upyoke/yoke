"""The merge result envelope reports the evidence record's own state.

A relayed evidence write that fails on one attempt and succeeds on retry,
and a landing re-entered after its close-out already completed, both used
to report a failed merge over a finished one: ``evidence_recorded=false``
beside a record that existed, and a "no active claim" refusal on an item
already merged, closed out, and terminal. These cases pin the envelope to
what the record says instead.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as sim_cli
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_git as merge_git
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION

MERGE_SHA = "b" * 40


@pytest.fixture(autouse=True)
def _receipt_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(receipts, "load", lambda *_a, **_k: None)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True,
                            capture_output=True, text=True)
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


def _item(repo: Path, *, status: str = "reviewing-implementation") -> dict:
    return {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": status,
        "workflow": {"id": "dash"},
        "worktrees": [{"branch": "ITEM-1",
                       "commit_sha": _git(repo, "rev-parse", "ITEM-1")}],
    }


def _section_response(content: str | None):
    """A stand-in for ``items.section.get`` over the evidence section."""
    if content is None:
        return SimpleNamespace(
            success=True, error=None,
            result={"section_name": DASH_EVIDENCE_SECTION, "found": False},
        )
    return SimpleNamespace(
        success=True, error=None,
        result={
            "section_name": DASH_EVIDENCE_SECTION,
            "found": True,
            "content": content,
        },
    )


def _evidence_content(merge_sha: str = MERGE_SHA) -> str:
    return json.dumps({
        "schema": 1,
        "result_summary": "landed",
        "verification_summary": "suite green",
        "verification_status": "passed",
        "commit_sha": "a" * 40,
        "merge_sha": merge_sha,
        "touched_files": ["feature.txt"],
        "recorded_at": "2026-01-01T00:00:00Z",
    })


def _wire_merge(monkeypatch: pytest.MonkeyPatch, repo: Path, item: dict) -> None:
    monkeypatch.setattr(sim_cli, "_resolve_item", lambda ref, project: (item, ""))
    monkeypatch.setattr(
        sim_cli, "_resolve_checkout", lambda _item, target: (repo, "main"),
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda item_id: None)
    monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id: None)
    monkeypatch.setattr(sim, "_run_merge_engine", lambda **_k: (0, ""))


class TestEvidenceWriteRetry:
    def test_a_refused_write_whose_row_exists_reports_it_recorded(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """The failed attempt's return is not the record's state."""
        _wire_merge(monkeypatch, repo, _item(repo))
        monkeypatch.setattr(sim_cli, "_session_holds_claim", lambda *_a: "")
        monkeypatch.setattr(
            evidence, "record",
            lambda **_k: "github graphql refused: Bad credentials",
        )
        asked: list[str] = []

        def covers(item_id: int, merge_sha: str) -> bool:
            asked.append(merge_sha)
            return True

        monkeypatch.setattr(evidence, "recorded_covers_merge", covers)
        transitions: list[str] = []

        def transition(**_kwargs: object) -> str:
            transitions.append("done")
            return ""

        monkeypatch.setattr(sim_cli.terminal, "transition_to_done", transition)

        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "suite green"],
        )
        envelope = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert envelope["evidence_recorded"] is True
        assert envelope["status"] == "done"
        # The refused attempt is still reported — as a warning, not as the
        # envelope's verdict on the record.
        assert any("Bad credentials" in w for w in envelope["warnings"])
        assert transitions == ["done"]
        # The record is consulted about this merge, not merely about the
        # item: a row from an earlier landing answers for that landing.
        assert asked and asked[0]

    def test_a_refused_write_with_no_row_still_fails(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        _wire_merge(monkeypatch, repo, _item(repo))
        monkeypatch.setattr(sim_cli, "_session_holds_claim", lambda *_a: "")
        monkeypatch.setattr(evidence, "record", lambda **_k: "relay refused")
        monkeypatch.setattr(
            evidence, "call_dispatcher",
            lambda **_k: _section_response(None),
        )
        monkeypatch.setattr(
            sim_cli.terminal, "transition_to_done",
            lambda **_k: pytest.fail("close-out must not continue"),
        )

        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "suite green"],
        )
        envelope = json.loads(capsys.readouterr().out)
        assert exit_code == 1
        assert envelope["evidence_recorded"] is False
        assert "evidence refused" in envelope["error"]

    def test_a_row_from_another_landing_is_not_this_merge_s_evidence(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            evidence, "call_dispatcher",
            lambda **_k: _section_response(_evidence_content("c" * 40)),
        )
        assert not evidence.recorded_covers_merge(7, MERGE_SHA)
        assert evidence.recorded_covers_merge(7, "c" * 40)


class TestTerminalTransitionConvergence:
    def test_a_transport_failure_surfaces_without_a_second_opinion(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """The transport owns the retry; this boundary owns the verdict.

        Asking the database whether the transition had secretly landed was a
        local patch over a relay that gave up after one try. The relay now
        spends an attempt budget with backoff, and a repeat carries the same
        request_id, so a transition that did land replays as success instead
        of needing to be discovered afterwards.
        """
        calls = []

        def dispatch(*, function_id, **_kwargs):
            calls.append(function_id)
            return SimpleNamespace(
                success=False,
                error=SimpleNamespace(
                    code="https_transport_failed",
                    message="connection dropped",
                ),
            )

        monkeypatch.setattr(terminal, "call_dispatcher", dispatch)
        monkeypatch.setattr(evidence, "call_dispatcher", dispatch)
        monkeypatch.setattr(merge_git, "is_landed", lambda *_a: True)
        monkeypatch.setattr(terminal.recovery, "claim_error", lambda *_a: "")

        error = terminal.transition_to_done(
            item_id=7,
            source_status="reviewing-implementation",
            repo_root=str(tmp_path),
            lane=LandedLane(branch="lane", target="main", commit_sha="a" * 40),
        )

        assert "connection dropped" in error
        assert calls == ["lifecycle.transition.execute"]

    def test_server_refusal_surfaces_without_authoritative_retry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        calls = []

        def dispatch(*, function_id, **_kwargs):
            calls.append(function_id)
            return SimpleNamespace(
                success=False,
                error=SimpleNamespace(code="transition_refused", message="denied"),
            )

        monkeypatch.setattr(terminal, "call_dispatcher", dispatch)
        monkeypatch.setattr(merge_git, "is_landed", lambda *_a: True)
        monkeypatch.setattr(terminal.recovery, "claim_error", lambda *_a: "")

        error = terminal.transition_to_done(
            item_id=7,
            source_status="reviewing-implementation",
            repo_root=str(tmp_path),
            lane=LandedLane(branch="lane", target="main", commit_sha="a" * 40),
        )

        assert error == "denied"
        assert calls == ["lifecycle.transition.execute"]


class TestClosedOutConvergence:
    def test_a_released_claim_on_a_closed_out_item_reports_the_landing(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """The terminal transition releases the claim; a retry says so."""
        _wire_merge(monkeypatch, repo, _item(repo, status="done"))
        monkeypatch.setattr(
            sim_cli, "_session_holds_claim",
            lambda *_a: "no live work claim on this item",
        )
        monkeypatch.setattr(
            evidence, "call_dispatcher",
            lambda **_k: _section_response(_evidence_content()),
        )
        monkeypatch.setattr(
            sim, "_run_merge_engine",
            lambda **_k: pytest.fail("a landed merge must not re-run"),
        )

        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "suite green"],
        )
        envelope = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert envelope["ok"] is True
        assert envelope["evidence_recorded"] is True
        assert envelope["already_merged"] is True
        assert envelope["merge_sha"] == MERGE_SHA
        assert envelope["touched_files"] == ["feature.txt"]
        assert envelope["status"] == "done"
        assert any("already closed out" in w for w in envelope["warnings"])

    def test_a_released_claim_with_no_evidence_stays_a_refusal(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        _wire_merge(monkeypatch, repo, _item(repo, status="done"))
        monkeypatch.setattr(
            sim_cli, "_session_holds_claim",
            lambda *_a: "no live work claim on this item",
        )
        monkeypatch.setattr(
            evidence, "call_dispatcher",
            lambda **_k: _section_response(None),
        )

        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "suite green"],
        )
        assert exit_code == 1
        assert "no live work claim" in capsys.readouterr().err

    def test_an_unfinished_item_keeps_its_claim_refusal(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Only a terminal item converges; anything earlier has work left."""
        _wire_merge(monkeypatch, repo, _item(repo))
        monkeypatch.setattr(
            sim_cli, "_session_holds_claim",
            lambda *_a: "work claim held by another session (other)",
        )
        monkeypatch.setattr(
            evidence, "call_dispatcher",
            lambda **_k: pytest.fail("an unfinished item reads no record"),
        )

        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "suite green"],
        )
        assert exit_code == 1
        assert "another session" in capsys.readouterr().err
