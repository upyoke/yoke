"""Custody is asked of a landing, and a run must both name it and carry it.

Every case here is one of the two halves of that conjunction failing on its
own. Membership without containment is a run that named the item before its
newest merge existed; containment without membership is a release that shipped
the code while owing the item nothing — and reading either one alone as
custody is what left merged items sitting with no release coming for them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    git,
    insert_run,
    item_ref,
    release_repository,
    serve_repository,
)
from yoke_core.domain.delivery_landing_custody import (
    HELD,
    REMERGED,
    UNDETERMINED,
    UNHELD,
    landing_custody,
    merged_open_items,
)
from yoke_core.domain.item_merge_receipt_document import record_entry


FLOW = "landing-custody-flow"
ITEM_ID = 9601
PROJECT_ID = 1


def _landed_item(conn: Any, *, status: str = "implementing") -> str:
    """One merged, still-open item, before its landing commit is known."""
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="blitz",
        status=status,
        deployment_flow=FLOW,
        merged_at="2026-09-14T00:10:00Z",
    )
    conn.commit()
    return item_ref(conn, ITEM_ID)


def _record_landing(conn: Any, merge_sha: str) -> None:
    """Name the commit this item's newest landing receipt carries."""
    record_entry(
        conn,
        item_id=ITEM_ID,
        branch=f"lane-{ITEM_ID}",
        target="main",
        merge_sha=merge_sha,
    )
    conn.commit()


def _two_landings(tmp_path: Path, ref: str) -> tuple[Path, str, str, str]:
    """A repository where one item landed twice, newest commit last."""
    repo, baseline, first = release_repository(tmp_path, ref)
    (repo / "release.txt").write_text("landed again\n", encoding="utf-8")
    git(repo, "commit", "-am", f"Land {ref} follow-up")
    return repo, baseline, first, git(repo, "rev-parse", "HEAD")


def _custody(conn: Any) -> Any:
    return landing_custody(conn, project_id=PROJECT_ID, item_ids=[ITEM_ID])[ITEM_ID]


def test_a_landing_no_run_names_is_unheld(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shape a cancelled release leaves behind: code out, nobody coming.

    A later release whose candidate happens to contain the merge is not
    custody of it — that run never named the item and owes it nothing.
    """
    ref = _landed_item(test_db)
    repo, _baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _record_landing(test_db, landing)
    insert_run(test_db, "run-later", lineage=landing, status="succeeded", flow=FLOW)

    verdict = _custody(test_db)

    assert verdict.state == UNHELD
    assert verdict.enrollable is True
    assert verdict.held is False


def test_a_member_run_carrying_the_landing_holds_it(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _landed_item(test_db)
    repo, _baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _record_landing(test_db, landing)
    insert_run(test_db, "run-holder", lineage=landing, status="created", flow=FLOW)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-holder',%s,'2026-09-14T00:30:00Z')",
        (ITEM_ID,),
    )
    test_db.commit()

    verdict = _custody(test_db)

    assert verdict.state == HELD
    assert verdict.run_id == "run-holder"
    assert verdict.enrollable is False


def test_a_membership_older_than_the_newest_merge_is_not_custody_of_it(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An item may land several times, and the runs can straddle the merges.

    The run named the item and delivered its first merge. The second merge is
    in no release at all, so the item is stranded for that landing however
    settled its membership looks.
    """
    ref = _landed_item(test_db)
    repo, _baseline, first, second = _two_landings(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _record_landing(test_db, second)
    insert_run(test_db, "run-first", lineage=first, status="succeeded", flow=FLOW)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-first',%s,'2026-09-14T00:30:00Z')",
        (ITEM_ID,),
    )
    test_db.commit()

    verdict = _custody(test_db)

    assert verdict.state == REMERGED
    assert verdict.run_id == "run-first"
    assert verdict.enrollable is True


def test_a_cancelled_member_run_holds_nothing(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run that ended without delivering releases what it named."""
    ref = _landed_item(test_db)
    repo, _baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _record_landing(test_db, landing)
    insert_run(
        test_db, "run-cancelled", lineage=landing, status="cancelled", flow=FLOW
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-cancelled',%s,'2026-09-14T00:30:00Z')",
        (ITEM_ID,),
    )
    test_db.commit()

    assert _custody(test_db).state == UNHELD


def test_an_unreadable_comparison_is_neither_answer(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No source could look, so nothing is known — and nothing is guessed."""
    ref = _landed_item(test_db)
    _repo, _baseline, landing = release_repository(tmp_path, ref)
    _record_landing(test_db, landing)
    insert_run(test_db, "run-holder", lineage=landing, status="created", flow=FLOW)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-holder',%s,'2026-09-14T00:30:00Z')",
        (ITEM_ID,),
    )
    test_db.commit()
    serve_repository(monkeypatch, None)

    verdict = _custody(test_db)

    assert verdict.state == UNDETERMINED
    assert verdict.enrollable is False
    assert verdict.reason
    assert verdict.recovery


def test_a_terminal_item_is_not_in_the_conversation(test_db: Any) -> None:
    """Shared with the steering report, so both agree on what "open" means."""
    _landed_item(test_db, status="done")

    assert [
        int(record["id"]) for record in merged_open_items(test_db, PROJECT_ID)
    ] == []
