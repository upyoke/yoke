"""Regression checks for canonical Browser method-case guidance."""

from __future__ import annotations

import re
from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO


TESTER = REPO / "runtime" / "agents" / "tester.md"
TESTER_BROWSER = REPO / "runtime" / "agents" / "tester-browser.md"
AGENT_OVERVIEW = REPO / "docs" / "agents.md"
CONDUCT_EPHEMERAL = (
    REPO / ".agents" / "skills" / "yoke" / "conduct" / "dispatch-context-ephemeral.md"
)
BROWSER_SUBSTRATE = REPO / "docs" / "browser-substrate.md"
CASE_ORCHESTRATION = REPO / "docs" / "browser-substrate" / "scenario-orchestration.md"
CANDIDATE_VERIFICATION = REPO / ".agents" / "skills" / "yoke" / "dash" / "verify.md"
TIMING_PROFILE = REPO / ".test_durations"
BROWSER_METHOD_MODULES = (
    REPO / "packages/yoke-core/src/yoke_core/domain/browser_qa_requirement.py",
    REPO / "packages/yoke-core/src/yoke_core/domain/qa_browser_evidence_check.py",
    REPO / "packages/yoke-core/src/yoke_core/domain/qa_gate_helpers.py",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing canonical Browser QA document: {path}"
    return path.read_text(encoding="utf-8")


def _case_run_block(text: str) -> str:
    match = re.search(r"yoke qa case run \\\n.*?```", text, re.DOTALL)
    assert match is not None, "missing multiline yoke qa case run recipe"
    return match.group(0)


def test_canonical_browser_docs_use_method_case_contract() -> None:
    paths = (
        TESTER,
        TESTER_BROWSER,
        AGENT_OVERVIEW,
        BROWSER_SUBSTRATE,
        CASE_ORCHESTRATION,
    )
    text = "\n".join(_read(path) for path in paths)

    assert "browser-check" in text
    assert "browser-inspection" in text
    assert "immutable `method_config`" in text
    assert "`expected_outcome`" in text
    assert "yoke qa case run" in text
    for retired in (
        "success_policy",
        "browser_smoke",
        "browser_diff",
        "yoke qa browser run",
    ):
        assert retired not in text


def test_tester_protocol_runs_each_case_with_freshness_identity() -> None:
    tester = _read(TESTER)
    protocol = _read(TESTER_BROWSER)
    recipe = _case_run_block(protocol)

    assert "tester-browser.md" not in tester
    assert "references/yoke-tester-browser.md" not in tester
    assert "--requirement-id <requirement-id>" in recipe
    assert '--base-url "<ephemeral-url>"' in recipe
    assert '--expected-branch "<worktree-branch>"' in recipe
    assert '--expected-sha "<worktree-head-sha>"' in recipe
    assert "Do not refine, replace, or otherwise rewrite `method_config`" in protocol


def test_conduct_dispatch_forwards_resolved_branch_and_sha_to_each_case() -> None:
    text = _read(CONDUCT_EPHEMERAL)
    recipe = _case_run_block(text)

    assert '_expected_browser_branch="${_worktree_branch}"' in text
    assert '_expected_browser_sha=$(git -C "${_worktree_path}" rev-parse HEAD)' in text
    assert '--expected-branch "{_expected_browser_branch}"' in recipe
    assert '--expected-sha "{_expected_browser_sha}"' in recipe
    assert "do not omit the\nexpected branch or SHA from any case invocation" in text


def test_browser_docs_link_candidate_verification() -> None:
    text = _read(BROWSER_SUBSTRATE) + _read(CASE_ORCHESTRATION)

    assert CANDIDATE_VERIFICATION.is_file()
    assert ".agents/skills/yoke/dash/verify.md" in text


def test_gate_recovery_names_the_registered_case_runners() -> None:
    text = _read(BROWSER_METHOD_MODULES[1])
    gates = (REPO / "packages/yoke-core/src/yoke_core/domain/qa_gates.py").read_text(
        encoding="utf-8"
    )
    for source in (text, gates):
        assert (
            "`yoke qa plan run --item {name} --transition {transition_name}`" in source
        )
        assert "`yoke qa case run --requirement-id <id>`" in source
        assert "retry the lifecycle transition" in source
        assert "/yoke " + "advance" not in source


def test_retired_browser_and_migration_residue_is_absent() -> None:
    browser_text = "\n".join(_read(path) for path in BROWSER_METHOD_MODULES)
    docs_text = _read(BROWSER_SUBSTRATE)
    timing_text = _read(TIMING_PROFILE)

    assert "legacy Browser case" not in browser_text
    assert "--qa-run-id" not in docs_text
    assert "qa artifact-add" not in docs_text
    assert "test_harness_session_project_identity.py" not in timing_text
