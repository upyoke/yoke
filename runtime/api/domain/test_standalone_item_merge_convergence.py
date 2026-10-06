"""Regression checks for standalone item merge convergence."""

from __future__ import annotations

from runtime.api.domain.test_standalone_item_merge_evidence_truth import (
    MERGE_SHA as MERGE_SHA,
    Path as Path,
    _evidence_content as _evidence_content,
    _item as _item,
    _no_candidate_review as _no_candidate_review,
    _receipt_free as _receipt_free,
    _section_response as _section_response,
    _wire_merge as _wire_merge,
    evidence as evidence,
    json as json,
    pytest as pytest,
    repo as repo,
    sim as sim,
    sim_cli as sim_cli,
)


class TestClosedOutConvergence:
    def test_a_released_claim_on_a_closed_out_item_reports_the_landing(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """The terminal transition releases the claim; a retry says so."""
        _wire_merge(monkeypatch, repo, _item(repo, status="done"))
        monkeypatch.setattr(
            sim_cli,
            "_session_holds_claim",
            lambda *_a: "no live work claim on this item",
        )
        monkeypatch.setattr(
            evidence,
            "call_dispatcher",
            lambda **_k: _section_response(_evidence_content()),
        )
        monkeypatch.setattr(
            sim,
            "_run_merge_engine",
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
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        _wire_merge(monkeypatch, repo, _item(repo, status="done"))
        monkeypatch.setattr(
            sim_cli,
            "_session_holds_claim",
            lambda *_a: "no live work claim on this item",
        )
        monkeypatch.setattr(
            evidence,
            "call_dispatcher",
            lambda **_k: _section_response(None),
        )

        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "suite green"],
        )
        assert exit_code == 1
        assert "no live work claim" in capsys.readouterr().err

    def test_an_unfinished_item_keeps_its_claim_refusal(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Only a terminal item converges; anything earlier has work left."""
        _wire_merge(monkeypatch, repo, _item(repo))
        monkeypatch.setattr(
            sim_cli,
            "_session_holds_claim",
            lambda *_a: "work claim held by another session (other)",
        )
        monkeypatch.setattr(
            evidence,
            "call_dispatcher",
            lambda **_k: pytest.fail("an unfinished item reads no record"),
        )

        exit_code = sim_cli.run(
            ["ITEM-1", "--result", "landed", "--verification", "suite green"],
        )
        assert exit_code == 1
        assert "another session" in capsys.readouterr().err
