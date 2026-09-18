"""Readiness across two hosts: one holds the item, the other holds the files.

The hosted API runs the checks for an item whose project it has never
checked out. The caller that asked usually has that checkout. These
cover the round trip — what the control plane publishes, what a machine
with the tree finds in it, and what the control plane does with the
answer — against a real spec and a real checkout.
"""

from __future__ import annotations

import subprocess

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import idea_readiness_checkout
from yoke_core.domain.idea_readiness_check import run_all_checks
from yoke_core.domain.idea_readiness_local_inputs import (
    build_local_execution_request,
    read_spec,
    spec_digest,
)
from yoke_core.domain.idea_readiness_results import (
    CLASS_UNAVAILABLE,
    VERDICT_PASS,
    VERDICT_UNAVAILABLE,
)
from yoke_core.engines import readiness_local_observations as local

_ITEM_ID = 4901
_BUDGET_PATH = "packages/yoke-core/src/yoke_core/domain/streamed_module.py"
_SPEC = (
    "Modify `yoke_core.domain.streamed_module.stream_rows` so it streams.\n"
    "\n"
    "## File Budget\n\n"
    f"- `{_BUDGET_PATH}` — current 120 lines; remaining headroom 230; "
    "at-or-over-limit: false; responsibility: streaming.\n"
)


@pytest.fixture
def item(test_db):
    return insert_item(
        test_db, id=_ITEM_ID, workflow_id="dash", status="idea", spec=_SPEC,
    )


@pytest.fixture
def project_checkout(tmp_path):
    """A real checkout whose files match what the spec records.

    Git-initialized because the observations are bound to a revision, and
    a registered project checkout is a git checkout.
    """
    root = tmp_path / "project"
    module = root / _BUDGET_PATH
    module.parent.mkdir(parents=True)
    module.write_text("def stream_rows():\n" + "    pass\n" * 119, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@example.com",
         "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        check=True,
    )
    return root


@pytest.fixture
def host_without_a_checkout(monkeypatch):
    monkeypatch.setattr(
        idea_readiness_checkout, "checkout_for_project_id", lambda project_id: None,
    )


def _request(conn) -> dict:
    return build_local_execution_request(conn, _ITEM_ID, read_spec(conn, _ITEM_ID))


def test_the_request_carries_what_the_checks_could_not_read(test_db, item) -> None:
    """Everything the file-reading checks need that is not a file."""
    request = _request(test_db)

    assert request["item_id"] == _ITEM_ID
    assert request["spec_text"] == _SPEC
    assert request["spec_sha256"] == spec_digest(_SPEC)
    assert request["project_id"] is not None
    assert request["checks"] == list(
        idea_readiness_checkout.CHECKOUT_DEPENDENT_CHECKS
    )


def test_the_answer_names_the_item_and_project_it_was_asked_about(
    test_db, item, project_checkout,
) -> None:
    """Identical spec text across two items is otherwise indistinguishable."""
    observations = local.collect(_request(test_db), project_checkout)

    assert observations["item_id"] == _ITEM_ID
    assert observations["project_id"] == _request(test_db)["project_id"]


def test_observations_from_a_matching_checkout_complete_the_run(
    test_db, item, host_without_a_checkout, project_checkout,
) -> None:
    observations = local.collect(_request(test_db), project_checkout)

    outcome = run_all_checks(test_db, _ITEM_ID, observations)

    assert outcome.unavailable == []
    assert outcome.verdict == VERDICT_PASS


def test_the_findings_are_the_ones_the_files_produce(
    test_db, item, host_without_a_checkout, project_checkout,
) -> None:
    """A file that drifted from its recorded sizing still blocks."""
    (project_checkout / _BUDGET_PATH).write_text("x\n" * 400, encoding="utf-8")

    observations = local.collect(_request(test_db), project_checkout)
    outcome = run_all_checks(test_db, _ITEM_ID, observations)

    assert "STALE_LINE_COUNT" in {issue.code for issue in outcome.issues}


def test_a_spec_rewritten_between_request_and_answer_is_not_a_pass(
    test_db, item, host_without_a_checkout, project_checkout,
) -> None:
    """The observing machine read a spec this run no longer holds."""
    observations = local.collect(_request(test_db), project_checkout)
    test_db.execute(
        "UPDATE items SET spec = %s WHERE id = %s",
        (_SPEC + "\n## Addendum\n", _ITEM_ID),
    )
    test_db.commit()

    outcome = run_all_checks(test_db, _ITEM_ID, observations)

    assert outcome.verdict == VERDICT_UNAVAILABLE
    assert outcome.classification == CLASS_UNAVAILABLE


def test_no_observations_still_reports_every_check_unperformed(
    test_db, item, host_without_a_checkout,
) -> None:
    """The existing answer is unchanged for a caller with no checkout either."""
    outcome = run_all_checks(test_db, _ITEM_ID)

    assert outcome.verdict == VERDICT_UNAVAILABLE
    assert [u.check for u in outcome.unavailable] == list(
        idea_readiness_checkout.CHECKOUT_DEPENDENT_CHECKS
    )
    assert all(u.retryable is False for u in outcome.unavailable)


def test_a_host_with_its_own_checkout_never_asks(
    test_db, item, monkeypatch, project_checkout,
) -> None:
    """Local mode reads its own tree; the handoff is for the case it cannot."""
    monkeypatch.setattr(
        idea_readiness_checkout,
        "checkout_for_project_id",
        lambda project_id: project_checkout,
    )

    outcome = run_all_checks(test_db, _ITEM_ID)

    assert outcome.unavailable == []


def test_a_machine_without_the_project_checkout_observes_nothing(
    test_db, item, monkeypatch,
) -> None:
    monkeypatch.setattr(
        local, "machine_checkout", lambda project_id: None,
    )

    assert local.collect_for_request(_request(test_db)) is None


def test_a_checkout_that_moved_mid_check_is_reported_moved(
    test_db, item, project_checkout, monkeypatch,
) -> None:
    revisions = iter(["before", "after"])
    monkeypatch.setattr(
        local, "checkout_revision", lambda repo_root: next(revisions),
    )

    observations = local.collect(_request(test_db), project_checkout)

    assert observations["checkout_moved"] is True


def test_an_unreadable_revision_is_reported_rather_than_assumed(
    test_db, item, project_checkout, monkeypatch,
) -> None:
    """A directory git cannot answer for yields no revision, not a fake one."""
    monkeypatch.setattr(local, "_git", lambda repo_root, *args: None)

    observations = local.collect(_request(test_db), project_checkout)

    assert observations["checkout_revision"] == ""
    assert observations["checkout_moved"] is False
