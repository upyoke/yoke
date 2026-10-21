"""Path-claim guards emit canonical claim-widen remediation."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import _read


def test_pre_edit_and_pre_bash_guards_already_emit_widen_remediation():
    """Pre-edit and pre-bash guard narratives teach canonical widen."""
    from yoke_core.domain import path_claim_bash_guard, path_claim_pre_edit_guard

    pre_edit = _read(Path(path_claim_pre_edit_guard.__file__).resolve())
    pre_bash = _read(Path(path_claim_bash_guard.__file__).resolve())
    assert "yoke claims path widen" in pre_edit
    assert "yoke claims path widen" in pre_bash
