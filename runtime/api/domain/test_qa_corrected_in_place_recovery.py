"""A replacement declaration for its own refreshed row teaches the working fix."""

import pytest

from yoke_core.domain import qa_requirement_replacement as replacement


def test_same_row_names_content_refresh_recovery(monkeypatch):
    row = {"id": 7, "plan_case_key": "corrected"}
    monkeypatch.setattr(replacement, "_row", lambda conn, rid: row)
    with pytest.raises(replacement.QaReplacementError) as caught:
        replacement._replacement_for(None, row, "corrected", [7], exact_scope=True)
    text = str(caught.value)
    assert "replacement_case_corrected_in_place" in text
    assert "Re-run without --replaces or --replaces-requirement" in text
    assert "new plan or case key" in text
