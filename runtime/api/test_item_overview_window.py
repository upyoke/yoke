"""Overview item window: live work plus terminals finished in the last 24h."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.timestamps import format_instant, parse_instant

from datetime import datetime, timedelta, timezone

from runtime.api.conftest import insert_item
from runtime.api.domain.handlers.items_read_test_support import request_for
from yoke_core.domain.actors import (
    actor_name,
    seed_human_actor,
    set_actor_name,
)
from yoke_core.domain.handlers import item_page_reads, items_listing


def _iso(hours_ago: int) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return format_instant(stamp)


def _titles(outcome) -> set[str]:
    return {row["title"] for row in outcome.result_payload["rows"]}


def _rows_by_title(outcome) -> dict:
    return {row["title"]: row for row in outcome.result_payload["rows"]}


def _finished(conn, item_id: int, status: str, hours_ago: int) -> str:
    """Record the lifecycle transition that put an item into *status*.

    Returns the stamp it wrote, because reading the clock a second time to
    name the same instant fails whenever the two reads straddle a second.
    """
    stamp = _iso(hours_ago)
    conn.execute(
        "INSERT INTO item_status_transitions "
        "(item_id, task_num, from_status, to_status, source, created_at) "
        "VALUES (%s, NULL, 'implementing', %s, 'test', %s)",
        (item_id, status, parse_instant(stamp)),
    )
    return stamp


def test_overview_keeps_live_and_recent_terminals(test_db):
    old = _iso(48)
    recent = _iso(2)
    insert_item(
        test_db,
        id=501,
        title="live-old",
        status="implementing",
        created_at=old,
        updated_at=old,
    )
    insert_item(
        test_db,
        id=502,
        title="done-recent",
        status="done",
        created_at=old,
        updated_at=old,
        merged_at=recent,
    )
    insert_item(
        test_db,
        id=503,
        title="done-old",
        status="done",
        created_at=old,
        updated_at=old,
        merged_at=old,
    )
    insert_item(
        test_db,
        id=504,
        title="cancelled-recent",
        status="cancelled",
        created_at=old,
        updated_at=recent,
    )
    _finished(test_db, 502, "done", 2)
    _finished(test_db, 503, "done", 48)
    _finished(test_db, 504, "cancelled", 2)
    test_db.commit()

    listing = items_listing.handle_items_list(
        request_for("items.list.run", {"fields": ["title"], "relevance": "overview"})
    )
    overview = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {"relevance": "overview"})
    )
    items_page = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {})
    )
    assert listing.primary_success and overview.primary_success
    assert items_page.primary_success
    expected = {"live-old", "done-recent", "cancelled-recent"}
    assert expected <= _titles(listing)
    assert expected <= _titles(overview)
    assert expected <= _titles(items_page)
    assert "done-old" not in _titles(listing)
    assert "done-old" not in _titles(overview)
    assert "done-old" in _titles(items_page)


def test_overview_resolves_each_owner_once(test_db, monkeypatch):
    actor_id = seed_human_actor(test_db)
    set_actor_name(test_db, actor_id, "Ada")
    old = _iso(48)
    for item_id, title in ((601, "owned-a"), (602, "owned-b")):
        insert_item(
            test_db,
            id=item_id,
            title=title,
            status="implementing",
            owner=str(actor_id),
            created_at=old,
            updated_at=old,
        )
    test_db.commit()
    calls: list[int] = []
    real = actor_name

    def counted(conn, value):
        calls.append(int(value))
        return real(conn, value)

    monkeypatch.setattr(
        "yoke_core.domain.actors.actor_name",
        counted,
    )
    outcome = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {})
    )
    assert outcome.primary_success
    owners = {
        row["owner_label"]
        for row in outcome.result_payload["rows"]
        if row["title"] in {"owned-a", "owned-b"}
    }
    assert owners == {f"Ada (actor id: {actor_id})"}
    assert calls.count(actor_id) == 1


def test_band_dates_an_item_by_its_finish_not_its_merge(test_db):
    """The merge and the finish are different moments, and only one is Done.

    Close-out trails the merge through release waits and item QA, so an item
    can land its code a day and a half before it ends and another can land an
    hour ago having ended long since. Dating the band by ``merged_at`` put
    each in exactly the wrong band.
    """
    old = _iso(48)
    insert_item(
        test_db,
        id=601,
        title="merged-long-ago-finished-now",
        status="done",
        created_at=old,
        updated_at=old,
        merged_at=_iso(30),
    )
    insert_item(
        test_db,
        id=602,
        title="merged-now-finished-long-ago",
        status="done",
        created_at=old,
        updated_at=_iso(1),
        merged_at=_iso(1),
    )
    _finished(test_db, 601, "done", 1)
    _finished(test_db, 602, "done", 30)
    test_db.commit()

    overview = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {"relevance": "overview"})
    )
    assert overview.primary_success
    titles = _titles(overview)
    assert "merged-long-ago-finished-now" in titles
    assert "merged-now-finished-long-ago" not in titles


def test_finished_facts_carry_the_transition_time(test_db):
    """The card's "finished" text reads the same instant the band sorts on."""
    old = _iso(48)
    insert_item(
        test_db,
        id=611,
        title="closed",
        status="done",
        created_at=old,
        updated_at=old,
        merged_at=_iso(30),
    )
    insert_item(
        test_db,
        id=612,
        title="still-going",
        status="implementing",
        created_at=old,
        updated_at=_iso(1),
    )
    finished_at = _finished(test_db, 611, "done", 3)
    test_db.commit()

    overview = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {"relevance": "overview"})
    )
    assert overview.primary_success
    rows = _rows_by_title(overview)
    assert rows["closed"]["finished"] is True
    assert rows["closed"]["terminal"] is True
    assert rows["closed"]["finished_at"] == parse_instant(finished_at)
    assert isinstance(rows["closed"]["finished_at"], datetime)
    # Not the merge, which is the whole point.
    assert rows["closed"]["finished_at"] != rows["closed"]["merged_at"]
    assert rows["still-going"]["finished"] is False
    assert rows["still-going"]["terminal"] is False
    assert rows["still-going"]["finished_at"] is None
    response = FunctionCallResponse(
        success=True,
        function="items.overview.list",
        version="v1",
        result=overview.result_payload,
    )
    wire_rows = {
        row["title"]: row for row in response.model_dump(mode="json")["result"]["rows"]
    }
    assert wire_rows["closed"]["finished_at"] == format_instant(finished_at)
    assert wire_rows["still-going"]["finished_at"] is None


def test_a_stopped_item_is_terminal_but_never_finished(test_db):
    """``stopped`` is a pause, so it releases resources without ending work.

    ``lifecycle.md`` calls it "Work halted unexpectedly or intentionally
    paused". Counting it as finished would report a halt as an accomplishment.
    """
    old = _iso(48)
    insert_item(
        test_db,
        id=621,
        title="halted",
        status="stopped",
        created_at=old,
        updated_at=_iso(1),
    )
    _finished(test_db, 621, "stopped", 1)
    test_db.commit()

    overview = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {"relevance": "overview"})
    )
    assert overview.primary_success
    row = _rows_by_title(overview)["halted"]
    assert row["terminal"] is True
    assert row["finished"] is False
    assert row["finished_at"] is None


def test_overview_card_keeps_first_successful_carried_build_outside_run_limit(test_db):
    import json

    from runtime.api.fixtures.backlog_inserts import insert_deployment_run
    from yoke_core.domain.deployment_run_item_delivery import first_carried_builds
    from yoke_core.domain.deployment_run_list_read import list_deployment_runs
    from yoke_core.domain.item_merge_receipt_document import record_entry

    item_id, project_id, stage_id = 619, 1, 7
    merge_sha = "a" * 40
    insert_item(test_db, id=item_id, title="carried and done", status="done")
    _finished(test_db, item_id, "done", 1)
    record_entry(
        test_db, item_id=item_id, branch="carried", target="main",
        commit_sha=merge_sha, merge_sha=merge_sha,
    )
    containment = json.dumps({"answers": [{
        "id": item_id, "project_id": project_id, "merge_sha": merge_sha, "state": "contained",
    }]})
    first = "run-carried-first"
    latest = "run-carried-later"
    for run_id, age in ((first, 6), (latest, 2)):
        insert_deployment_run(
            test_db, id=run_id, project_id=project_id,
            created_at=_iso(age + 1), completed_at=_iso(age),
            status="succeeded", target_tier="persistent", target_environment_id=stage_id,
            candidate_containment=containment,
        )
    test_db.execute("UPDATE environments SET name='stage' WHERE id=%s", (stage_id,))
    test_db.commit()

    runs = list_deployment_runs(project="yoke", status=None, limit=1, relevance="overview")
    assert [run["id"] for run in runs] == [latest]
    assert runs[0]["delivery_candidate_items"] == []

    overview = item_page_reads.handle_items_overview_list(
        request_for("items.overview.list", {"relevance": "overview"})
    )
    assert overview.primary_success
    card = _rows_by_title(overview)["carried and done"]
    assert card["delivery"]["carried_builds"] == [{
        "id": first, "project_id": project_id, "target_environment": "stage",
    }]

    landings = {(project_id, item_id, merge_sha)}
    assert first_carried_builds(test_db, landings, readable_project_ids=set()) == {}
    test_db.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) VALUES (%s, %s, now())",
        (first, item_id),
    )
    assert first_carried_builds(test_db, landings, readable_project_ids={project_id}) == {}
