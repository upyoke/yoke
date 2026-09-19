"""Merge evidence is owed by the landing, not by the status change."""

from __future__ import annotations

from runtime.api.domain.test_standalone_item_merge_close_out_report import (
    SESSION,
    _outcome_block,
    _run_close_out,
)
from yoke_core.domain import standalone_item_merge_close_out_report as report


def test_a_merge_that_skips_close_out_still_records_supplied_evidence(
    monkeypatch, capsys
):
    """Evidence describes the landing, not the status change.

    A caller that hands over the result and verification has already done
    the work the record describes, and the landing it describes has now
    happened. Withholding the write until the status flip meant a merge that
    deferred its terminal transition left no record of what it landed.
    """
    _run_close_out(
        monkeypatch,
        argv=[
            "ITEM-1",
            "--skip-status",
            "--result",
            "landed",
            "--verification",
            "green",
            "--session-id",
            SESSION,
        ],
    )

    block = _outcome_block(capsys.readouterr().err)
    assert block[0] == "ITEM-1 not closed"
    assert f"  evidence saved: yes — {report.EVIDENCE_WRITTEN_NOTE}" in block
