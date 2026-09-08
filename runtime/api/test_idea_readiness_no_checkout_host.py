"""Readiness on a host with no project checkout, end to end.

The hosted API host runs the readiness checks against items whose files it
does not have, and it never will: project checkouts are not installed there.
Three failure shapes are covered here — the crash the file-reading checks
used to raise, the silent substitution of whatever tree the process stood
in, and reporting an unperformed check as passed.

The fixture is deliberately harsher than the hosted host: no ``.git``
ancestor, no ``git`` executable on PATH, no ``YOKE_REPO_ROOT``, and a
working directory that is not a checkout of anything.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import idea_readiness_checkout
from yoke_core.domain.idea_readiness_check import run_all_checks
from yoke_core.domain.idea_readiness_checkout import (
    CHECKOUT_DEPENDENT_CHECKS,
    CHECKOUT_UNAVAILABLE_REASON,
)
from yoke_core.domain.idea_readiness_results import (
    CLASS_UNAVAILABLE,
    VERDICT_UNAVAILABLE,
)

_SPEC_NEEDING_FILES = (
    "Modify `yoke_core.domain.no_such_module.no_such_function` so it streams.\n"
    "\n"
    "## File Budget\n\n"
    "- `packages/yoke-core/src/yoke_core/domain/no_such_module.py` — current "
    "120 lines; remaining headroom 230; at-or-over-limit: false; "
    "responsibility: streaming.\n"
)


@pytest.fixture
def host_without_a_checkout(tmp_path, monkeypatch):
    """A host that has no checkout for the item's project, and no way to fake one."""
    monkeypatch.setattr(
        idea_readiness_checkout, "checkout_for_project_id", lambda project_id: None,
    )
    elsewhere = tmp_path / "not-a-checkout"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("YOKE_REPO_ROOT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    return elsewhere


@pytest.fixture
def item_needing_files(test_db):
    return insert_item(
        test_db,
        id=4801,
        workflow_id="dash",
        status="idea",
        spec=_SPEC_NEEDING_FILES,
    )


def test_checks_needing_files_are_reported_unperformed_not_passed(
    host_without_a_checkout, item_needing_files, test_db,
):
    outcome = run_all_checks(test_db, 4801)

    assert outcome.verdict == VERDICT_UNAVAILABLE
    assert outcome.classification == CLASS_UNAVAILABLE
    assert [u.check for u in outcome.unavailable] == list(CHECKOUT_DEPENDENT_CHECKS)


def test_no_invented_missing_file_failures(
    host_without_a_checkout, item_needing_files, test_db,
):
    """The spec names a module that exists nowhere; absence is not a finding here."""
    outcome = run_all_checks(test_db, 4801)

    codes = {issue.code for issue in outcome.issues}
    assert "UNRESOLVED_MODULE" not in codes
    assert "UNRESOLVED_FUNCTION" not in codes
    assert "STALE_LINE_COUNT" not in codes


def test_each_unperformed_check_names_a_supported_recovery(
    host_without_a_checkout, item_needing_files, test_db,
):
    outcome = run_all_checks(test_db, 4801)

    for unperformed in outcome.unavailable:
        assert unperformed.reason == CHECKOUT_UNAVAILABLE_REASON
        assert unperformed.retryable is False
        assert unperformed.check in unperformed.recovery
        assert "not installed on the hosted API host" in unperformed.recovery


def test_advisories_are_absent_rather_than_reported_clean(
    host_without_a_checkout, item_needing_files, test_db,
):
    """An empty advisory list would read as "checked, nothing found"."""
    outcome = run_all_checks(test_db, 4801)

    assert outcome.advisories == []
    assert "collect_symlink_advisories" in {u.check for u in outcome.unavailable}


def test_checks_needing_no_files_still_run(
    host_without_a_checkout, test_db,
):
    """A File Budget the workflow requires is still enforced without a checkout."""
    insert_item(
        test_db,
        id=4802,
        workflow_id="dash",
        status="refining-idea",
        workflow_posture=json.dumps({"file_budget": True}),
        spec="## File Budget\n",
    )

    outcome = run_all_checks(test_db, 4802)

    assert "MISSING_FILE_BUDGET" in {issue.code for issue in outcome.issues}
    assert outcome.verdict == "block"


def test_mapped_checkout_is_used_when_the_host_has_one(
    tmp_path, monkeypatch, item_needing_files, test_db,
):
    """The resolved tree is the item project's checkout, not the process cwd."""
    project_checkout = tmp_path / "project"
    module = (
        project_checkout
        / "packages/yoke-core/src/yoke_core/domain/no_such_module.py"
    )
    module.parent.mkdir(parents=True)
    module.write_text("x\n" * 120, encoding="utf-8")
    monkeypatch.setattr(
        idea_readiness_checkout,
        "checkout_for_project_id",
        lambda project_id: project_checkout,
    )
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    outcome = run_all_checks(test_db, 4801)

    assert outcome.unavailable == []
    assert "STALE_LINE_COUNT" not in {issue.code for issue in outcome.issues}


def test_resolver_reads_the_item_project_not_the_ambient_tree(
    tmp_path, monkeypatch, item_needing_files, test_db,
):
    """The project id handed to the checkout mapping is the item's own."""
    seen: list = []

    def _record(project_id):
        seen.append(project_id)
        return None

    monkeypatch.setattr(
        idea_readiness_checkout, "checkout_for_project_id", _record,
    )
    monkeypatch.chdir(tmp_path)

    run_all_checks(test_db, 4801)

    assert seen and all(isinstance(pid, int) for pid in seen)
