"""Reads ask each shared question once, not once per row they show.

Every read covered here used to issue a query per row for something the
rows share — the project's lane settings, the actor's name, the item's
public ref, the document an item is linked to. Counting statements is the
only way to state that property: a timing drifts with the machine, while
"one statement however many rows" is what the code is supposed to hold.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_contracts.project_contract.project_keys import (
    SESSION_ROUTING_CAPABILITY,
)
from yoke_core.domain.actor_render import actor_display_labels, render_actor_names
from yoke_core.domain.deployment_item_flow_resolution import (
    item_completion_flow,
    item_completion_flows,
)
from yoke_core.domain.session_presentation_read import lane_settings_by_project
from yoke_core.domain.sessions_list_rows import render_session_roster_rows
from yoke_core.domain.steering_scope_membership import (
    item_document_link,
    item_document_links,
)

def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_actor(conn, actor_id: int, name: str) -> None:
    conn.execute(
        "INSERT INTO actors (id, kind, name, created_at) "
        "VALUES (%s, 'human', %s, %s) ON CONFLICT (id) DO NOTHING",
        (actor_id, name, _iso()),
    )
    conn.commit()


def _link_document(conn, item_id: int, slug: str, *, project_id: int = 1) -> None:
    """Link an item to a strategy document the way intake and linking do."""
    conn.execute(
        "INSERT INTO strategy_docs (project_id, slug, content, updated_at) "
        "VALUES (%s, %s, '', %s) ON CONFLICT DO NOTHING",
        (project_id, slug, _iso()),
    )
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (item_id, project_id, slug, _iso()),
    )
    conn.commit()


def _roster_row(session_id: str, *, project_id: int, actor_id: int, item_id: int):
    """The columns the roster renderer reads off one fetched session row."""
    return {
        "session_id": session_id,
        "project_id": project_id,
        "actor_id": actor_id,
        "current_item_id": str(item_id),
        "executor": "claude-code",
        "executor_surface": "claude-cli",
        "execution_lane": "primary",
        "mode": "wait",
        "last_heartbeat": _iso(),
        "last_tool_call_at": _iso(),
    }


def _render(conn, rows):
    return render_session_roster_rows(
        conn,
        rows,
        liveness=None,
        claims_by_session={},
        roles_by_session={},
        item_holders={},
        holdings_by_session={},
        blitz_lanes_by_session={},
    )


class TestRosterPageQuestions:
    def test_lane_settings_read_once_for_every_project_on_the_page(self, test_db):
        for project_id in (1, 2):
            test_db.execute(
                "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (project_id, type) DO NOTHING",
                (project_id, SESSION_ROUTING_CAPABILITY, "{}", _iso()),
            )
        test_db.commit()
        counting = CountingConnection(test_db)

        settings = lane_settings_by_project(counting, [1, 2, 1, 2, 1, None])

        assert set(settings) == {1, 2}
        assert counting.count == 1

    def test_roster_render_cost_does_not_grow_with_row_count(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        _insert_actor(test_db, 7, "Roster Reader")
        for item_id in range(201, 209):
            insert_item(test_db, id=item_id, title=f"row {item_id}")
        test_db.commit()

        small = [
            _roster_row(f"s-{n}", project_id=1, actor_id=7, item_id=200 + n)
            for n in range(1, 3)
        ]
        large = [
            _roster_row(f"s-{n}", project_id=1, actor_id=7, item_id=200 + n)
            for n in range(1, 9)
        ]

        small_conn = CountingConnection(test_db)
        small_rows = _render(small_conn, small)
        large_conn = CountingConnection(test_db)
        large_rows = _render(large_conn, large)

        assert len(small_rows) == 2 and len(large_rows) == 8
        assert small_conn.count == large_conn.count

    def test_roster_render_resolves_the_refs_and_labels_it_shows(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        _insert_actor(test_db, 8, "Named Holder")
        insert_item(test_db, id=311, title="held work")
        test_db.commit()

        rendered = _render(
            test_db,
            [_roster_row("s-named", project_id=1, actor_id=8, item_id=311)],
        )

        assert rendered[0]["actor_label"] == "Named Holder"
        assert rendered[0]["current_item"] == "YOK-311"


class TestActorNameReads:
    def test_names_for_a_set_cost_one_statement(self, test_db):
        for actor_id, name in ((11, "Ada"), (12, "Grace"), (13, "Alan")):
            _insert_actor(test_db, actor_id, name)
        counting = CountingConnection(test_db)

        names = render_actor_names(counting, [11, 12, 13, 11, None, "nope"])

        assert names == {11: "Ada", 12: "Grace", 13: "Alan"}
        assert counting.count == 1

    def test_display_labels_for_a_set_cost_one_statement(self, test_db):
        for actor_id, name in ((21, "Sam"), (22, "Sam"), (23, "Robin")):
            _insert_actor(test_db, actor_id, name)
        counting = CountingConnection(test_db)

        labels = actor_display_labels(counting, [21, 22, 23])

        assert labels == {
            21: "Sam (actor 21)",
            22: "Sam (actor 22)",
            23: "Robin",
        }
        assert counting.count == 1

    def test_display_label_names_an_actor_with_no_row(self, test_db):
        assert actor_display_labels(test_db, [9_001]) == {9_001: "actor 9001"}


class TestItemDocumentLinks:
    def test_links_for_a_set_cost_one_read_beyond_the_schema_probe(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        for item_id in (401, 402, 403):
            insert_item(test_db, id=item_id, title=f"linked {item_id}")
        for item_id, slug in ((401, "CURRENT-PLAN"), (402, "AREA-PLAN")):
            _link_document(test_db, item_id, slug)
        counting = CountingConnection(test_db)

        links = item_document_links(counting, [401, 402, 403, 401])

        assert links == {401: (1, "CURRENT-PLAN"), 402: (1, "AREA-PLAN")}
        # One link read for the set; the rest is the schema probe the single
        # form pays once too.
        link_reads = sum(
            count
            for sql, count in counting.statements.items()
            if sql.startswith("SELECT item_id") and "item_strategy_docs" in sql
        )
        assert link_reads == 1

    def test_single_link_matches_the_set_form(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        insert_item(test_db, id=411, title="linked once")
        test_db.commit()
        _link_document(test_db, 411, "CURRENT-PLAN")

        assert item_document_link(test_db, 411) == (1, "CURRENT-PLAN")
        assert item_document_link(test_db, 412) is None


class TestItemCompletionFlows:
    def test_set_form_matches_the_single_form_for_every_item(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        insert_item(test_db, id=501, title="pinned", deployment_flow="flow-a")
        insert_item(test_db, id=502, title="pinned too", deployment_flow="flow-b")
        insert_item(test_db, id=503, title="unpinned")
        test_db.commit()

        batched = item_completion_flows(test_db, [501, 502, 503])

        assert batched == {
            item_id: item_completion_flow(test_db, item_id)
            for item_id in (501, 502, 503)
        }
        assert batched[501] == "flow-a"

    def test_the_item_rows_come_back_in_one_statement(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        for item_id in (511, 512, 513, 514):
            insert_item(test_db, id=item_id, title=f"flow {item_id}", deployment_flow="f")
        test_db.commit()
        counting = CountingConnection(test_db)

        item_completion_flows(counting, [511, 512, 513, 514])

        item_reads = [
            sql for sql in counting.statements if sql.startswith("SELECT i.id,")
        ]
        assert len(item_reads) == 1
        assert counting.statements[item_reads[0]] == 1
