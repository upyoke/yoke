"""The merge result envelope reports the evidence record's own state.

A relayed evidence write that fails on one attempt and succeeds on retry,
and a landing re-entered after its close-out already completed, both used
to report a failed merge over a finished one: ``evidence_recorded=false``
beside a record that existed, and a "no active claim" refusal on an item
already merged, closed out, and terminal. These cases pin the envelope to
what the record says instead.
"""

from __future__ import annotations

from runtime.api.domain.standalone_item_merge_evidence_truth_test_support import (MERGE_SHA as MERGE_SHA, _evidence_content as _evidence_content, _item as _item, _no_candidate_review as _no_candidate_review, _receipt_free as _receipt_free, _section_response as _section_response, _wire_merge as _wire_merge, repo as repo, sim as sim)
from runtime.api.domain.dash_posture_deployment_containment_test_support import (_git as _git)


import json as json
from pathlib import Path as Path
from types import SimpleNamespace

import pytest as pytest

from yoke_core.domain import standalone_item_merge_cli as sim_cli
from yoke_core.domain import (
    standalone_item_merge_close_out_transition as close_out_transition,
)
from yoke_core.domain.standalone_item_merge_release_status import CloseOutRoute
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_git as merge_git
from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain.standalone_item_merge_landed import LandedLane


class TestEvidenceWriteRetry:
    def test_a_refused_write_whose_row_exists_reports_it_recorded(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """The failed attempt's return is not the record's state."""
        _wire_merge(monkeypatch, repo, _item(repo))
        monkeypatch.setattr(sim_cli, "_session_holds_claim", lambda *_a: "")
        monkeypatch.setattr(
            evidence,
            "record",
            lambda **_k: "github graphql refused: Bad credentials",
        )
        asked: list[str] = []

        def covers(item_id: int, merge_sha: str) -> bool:
            asked.append(merge_sha)
            return True

        monkeypatch.setattr(evidence, "recorded_covers_merge", covers)
        monkeypatch.setattr(
            close_out_transition,
            "close_out_route",
            lambda *_a, **_k: CloseOutRoute(stages=("done",)),
        )
        transitions: list[str] = []

        def transition(**_kwargs: object) -> tuple[str, str]:
            transitions.append("done")
            return "done", ""

        monkeypatch.setattr(terminal, "transition_to_done", transition)

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
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        _wire_merge(monkeypatch, repo, _item(repo))
        monkeypatch.setattr(sim_cli, "_session_holds_claim", lambda *_a: "")
        monkeypatch.setattr(evidence, "record", lambda **_k: "relay refused")
        monkeypatch.setattr(
            evidence,
            "call_dispatcher",
            lambda **_k: _section_response(None),
        )
        monkeypatch.setattr(
            terminal,
            "transition_to_done",
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
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            evidence,
            "call_dispatcher",
            lambda **_k: _section_response(_evidence_content("c" * 40)),
        )
        assert not evidence.recorded_covers_merge("ITEM-7", MERGE_SHA)
        assert evidence.recorded_covers_merge("ITEM-7", "c" * 40)


class TestTerminalTransitionConvergence:
    def test_a_transport_failure_surfaces_without_a_second_opinion(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
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

        new_status, error = terminal.transition_to_done(
            item_id="ITEM-7",
            source_status="reviewing-implementation",
            repo_root=str(tmp_path),
            lane=LandedLane(branch="lane", target="main", commit_sha="a" * 40),
        )

        assert new_status == ""
        assert "connection dropped" in error
        assert calls == ["lifecycle.transition.execute"]

    def test_server_refusal_surfaces_without_authoritative_retry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
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

        new_status, error = terminal.transition_to_done(
            item_id="ITEM-7",
            source_status="reviewing-implementation",
            repo_root=str(tmp_path),
            lane=LandedLane(branch="lane", target="main", commit_sha="a" * 40),
        )

        assert new_status == ""
        assert error == "denied"
        assert calls == ["lifecycle.transition.execute"]
