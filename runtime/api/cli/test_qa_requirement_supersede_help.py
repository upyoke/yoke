"""Supersede help names only recoveries the requirement commands accept."""

from __future__ import annotations

from yoke_cli.commands.adapters.qa_requirement_supersede import _EPILOG
from yoke_core.domain.qa_requirement_config_update import (
    UPDATABLE_REQUIREMENT_FIELDS,
)


def test_unjudged_case_recovery_matches_what_update_accepts() -> None:
    text = " ".join(_EPILOG.split())

    assert "still correctable in place" not in text
    for field in ("instructions", "expected_outcome"):
        assert field not in UPDATABLE_REQUIREMENT_FIELDS
        assert field in text
    assert "method_config" in UPDATABLE_REQUIREMENT_FIELDS
    assert "'yoke qa requirement add'" in text
    assert "'yoke qa requirement waive'" in text
