"""The item's requirement rows carry the runner that owns each requirement.

The merge boundary's commit-bound recovery classifies a requirement by its
runner: a command runner is re-executed against the new candidate, and
anything else is refused as substrate-owned evidence the merge cannot
re-bind. It reads that runner off the item's ``qa_requirements`` projection.

A projection that omits the column makes every requirement unclassifiable,
so recovery refuses work it could have re-run and names the runner as
``<missing>`` in a refusal about a runner the row records perfectly well.
The runner is stored in two places -- on the requirement when it overrides,
and otherwise on its method -- so the projection has to answer with the one
that actually governs.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.item_detail_qa import qa_rows


def _row(conn, item_id: int, requirement_id: int) -> dict:
    rows = [r for r in qa_rows(conn, item_id) if int(r["id"]) == requirement_id]
    assert rows, f"requirement {requirement_id} missing from the projection"
    return rows[0]


def test_a_requirement_reports_the_runner_its_method_declares() -> None:
    """The common shape: the method owns the runner, the requirement defers."""
    with test_database() as conn:
        insert_item(conn, id=4701, title="Method-owned runner")
        requirement = insert_qa_requirement(
            conn, item_id=4701, method_id="command-ci",
        )

        row = _row(conn, 4701, int(requirement["id"]))

        assert row["runner_id"] == "ci_run"


def test_a_requirement_reports_its_own_runner_over_its_method() -> None:
    """An override on the row is the runner that will actually execute it."""
    with test_database() as conn:
        insert_item(conn, id=4702, title="Requirement-owned runner")
        requirement = insert_qa_requirement(
            conn,
            item_id=4702,
            method_id="command-ci",
            runner_id="worktree_run",
        )

        row = _row(conn, 4702, int(requirement["id"]))

        assert row["runner_id"] == "worktree_run"


def test_a_requirement_with_no_method_reports_no_runner() -> None:
    """A hand-recorded acceptance has no runner, and must not acquire one.

    Recovery re-records this shape rather than re-running it, and it tells
    the two apart by both the method and the runner being absent.
    """
    with test_database() as conn:
        insert_item(conn, id=4703, title="Hand-recorded acceptance")
        requirement = insert_qa_requirement(conn, item_id=4703, method_id=None)

        row = _row(conn, 4703, int(requirement["id"]))

        assert not row["runner_id"]
        assert not row["method_id"]
