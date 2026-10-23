"""A replacement declaration for its own refreshed row teaches the retry."""

import pytest

from yoke_core.domain import qa_requirement_replacement as replacement


def test_same_row_names_the_fresh_attempt_retry(monkeypatch):
    row = {"id": 7, "plan_case_key": "corrected"}
    monkeypatch.setattr(replacement, "_row", lambda conn, rid: row)
    with pytest.raises(replacement.QaReplacementError) as caught:
        replacement._replacement_for(None, row, "corrected", [7], exact_scope=True)
    text = str(caught.value)
    assert "replacement_case_corrected_in_place" in text
    assert "retry that requirement with `yoke qa plan run`" in text
    assert "no --replaces" in text


def test_real_successor_is_selected_when_materialization_also_contains_failed_row(monkeypatch):
    failed = {"id": 7, "plan_case_key": "corrected"}
    successor = {"id": 8, "plan_case_key": "corrected", "replacement_requirement_id": None, "blocking_mode": "blocking"}
    monkeypatch.setattr(replacement, "_row", lambda conn, rid: {7: failed, 8: successor}[rid])
    monkeypatch.setattr(replacement, "obligation_settled", lambda row: False)
    monkeypatch.setattr(replacement, "same_scope", lambda left, right: [])
    assert replacement._replacement_for(None, failed, "corrected", [7, 8]) == successor
