"""The approval step an install reports for the hook glue it just wrote.

A harness re-requires approval whenever the file it hashed changes, so an
update owes the operator the same sentence a fresh write does — and a
reconcile that changed nothing owes none.
"""

from __future__ import annotations

import pytest

from yoke_cli.project_install.hook_trust_report import REPORT_KEY
from yoke_contracts.harness_hook_approval import HARNESS_HOOK_APPROVAL
from yoke_core.domain.project_install import apply_bundle
from yoke_core.domain.project_install_test_helpers import (
    codex_hooks,
    entry,
    make_bundle,
)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _codex_lines(report) -> list[str]:
    surface = HARNESS_HOOK_APPROVAL["codex"]["trust_surface"]
    return [line for line in report[REPORT_KEY] if surface in line]


def test_fresh_write_names_the_approval_step_and_why_it_returns(repo):
    report = apply_bundle(repo, make_bundle(), source="test")

    lines = _codex_lines(report)
    assert len(lines) == 1
    assert HARNESS_HOOK_APPROVAL["codex"]["grant_scope"] in lines[0]
    assert "silently" in lines[0]


def test_updating_the_glue_names_the_approval_step_again(repo):
    apply_bundle(repo, make_bundle(), source="test")

    updated = codex_hooks()
    updated["PreToolUse"].append(entry("yoke hook evaluate PreToolUse", "Edit"))
    report = apply_bundle(repo, make_bundle(codex=updated), source="test")

    assert len(_codex_lines(report)) == 1


def test_a_reconcile_that_changed_nothing_names_nothing(repo):
    apply_bundle(repo, make_bundle(), source="test")

    report = apply_bundle(repo, make_bundle(), source="test")

    assert report[REPORT_KEY] == []
