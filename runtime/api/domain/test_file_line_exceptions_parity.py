"""The two file-line checker copies must share built-in policy defaults."""

from __future__ import annotations

import pathlib

from yoke_contracts.project_contract import file_line_policy as contract
from yoke_core.domain import file_line_check as core_gate
from yoke_harness.git_hooks import file_line_check as harness_gate


def test_both_gate_copies_share_default_exception_globs() -> None:
    shared = contract.default_exception_globs()
    assert core_gate.TEMPORARY_EXCEPTIONS == shared
    assert harness_gate.TEMPORARY_EXCEPTIONS == shared
    assert core_gate.TEMPORARY_EXCEPTIONS == harness_gate.TEMPORARY_EXCEPTIONS


def test_both_gate_copies_share_tracked_generated_views(
    tmp_path: pathlib.Path,
) -> None:
    for rel in contract.tracked_generated_views():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated\n", encoding="utf-8")
        assert core_gate.classify_path(rel, repo_root=tmp_path).value == "generated"
        assert harness_gate.classify_path(rel, repo_root=tmp_path).value == "generated"


def test_pack_receipt_is_machine_generated_but_installed_files_are_authored(
    tmp_path: pathlib.Path,
) -> None:
    receipt = tmp_path / ".yoke/packs.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("{}\n", encoding="utf-8")
    installed = tmp_path / "ops/project-owned.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("print('owned')\n", encoding="utf-8")

    assert (
        core_gate.classify_path(".yoke/packs.json", repo_root=tmp_path).value
        == "generated"
    )
    assert (
        harness_gate.classify_path(".yoke/packs.json", repo_root=tmp_path).value
        == "generated"
    )
    assert (
        core_gate.classify_path("ops/project-owned.py", repo_root=tmp_path).value
        == "authored"
    )
    assert (
        harness_gate.classify_path("ops/project-owned.py", repo_root=tmp_path).value
        == "authored"
    )


def test_default_exceptions_are_project_contract_wide_not_yoke_specific() -> None:
    # Rendered strategy views are untracked local renders, so no built-in
    # exception glob exists; project-local additions come from
    # .yoke/file-line-exceptions.
    assert core_gate.TEMPORARY_EXCEPTIONS == ()
    assert "packaging/public-installer/install" not in core_gate.TEMPORARY_EXCEPTIONS


def test_packaged_install_bundle_mirrors_are_generated(
    tmp_path: pathlib.Path,
) -> None:
    rel = (
        "packages/yoke-core/src/yoke_core/install_bundle_tree/"
        "runtime/harness/claude/agents/yoke-architect.md"
    )
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_text("generated\n", encoding="utf-8")
    assert core_gate.classify_path(rel, repo_root=tmp_path).value == "generated"
    assert harness_gate.classify_path(rel, repo_root=tmp_path).value == "generated"
