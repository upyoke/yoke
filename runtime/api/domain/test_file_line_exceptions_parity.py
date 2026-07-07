"""The two file-line checker copies must share built-in policy defaults."""

from __future__ import annotations

from yoke_contracts.project_contract import file_line_policy as contract
from yoke_core.domain import file_line_check as core_gate
from yoke_harness.git_hooks import file_line_check as harness_gate


def test_both_gate_copies_share_default_exception_globs() -> None:
    shared = contract.default_exception_globs()
    assert core_gate.TEMPORARY_EXCEPTIONS == shared
    assert harness_gate.TEMPORARY_EXCEPTIONS == shared
    assert core_gate.TEMPORARY_EXCEPTIONS == harness_gate.TEMPORARY_EXCEPTIONS


def test_default_exceptions_are_project_contract_wide_not_yoke_specific() -> None:
    # Rendered strategy views are untracked local renders, so no built-in
    # exception glob exists; project-local additions come from
    # .yoke/file-line-exceptions.
    assert core_gate.TEMPORARY_EXCEPTIONS == ()
    assert "packaging/public-installer/install" not in core_gate.TEMPORARY_EXCEPTIONS
