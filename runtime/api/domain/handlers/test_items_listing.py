"""Handler coverage for items.list.run / items.search.run."""

from __future__ import annotations

from runtime.api.conftest import insert_item
from yoke_core.domain.actor_permissions import (
    ROLE_VIEWER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import items_listing
from yoke_core.domain.org_schema import org_id_by_slug
from yoke_core.domain.project_identity import resolve_project_id
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(function_id: str, payload=None, actor_id="op") -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _grant_project_viewer(conn, project: str) -> int:
    return _grant_project_viewer_id(conn, resolve_project_id(conn, project))


def _grant_project_viewer_id(conn, project_id: int) -> int:
    seed_roles_and_permissions(conn)
    actor_id = seed_human_actor(conn)
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=ROLE_VIEWER,
        granted_by_actor_id=actor_id,
    )
    return actor_id


def _insert_shared_slug_items(conn) -> tuple[int, int]:
    default_org = org_id_by_slug(conn, "default")
    assert default_org is not None
    other_org = conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES ('other', 'Other Org', '2026-01-01T00:00:00Z') "
        "RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO projects "
        "(id, org_id, slug, name, public_item_prefix, created_at) "
        "VALUES "
        "(110, %s, 'shared', 'Default Shared', 'DSH', '2026-01-01T00:00:00Z'), "
        "(111, %s, 'shared', 'Other Shared', 'OSH', '2026-01-01T00:00:00Z')",
        (default_org, other_org),
    )
    insert_item(conn, id=910, title="shared zorp default", project_id=110)
    insert_item(conn, id=911, title="shared zorp other", project_id=111)
    return 110, 111


class TestItemsList:
    def test_filters_by_status_with_default_fields(self, test_db):
        insert_item(test_db, id=1, title="Done thing", status="done")
        insert_item(test_db, id=2, title="Open thing", status="idea")
        test_db.commit()
        outcome = items_listing.handle_items_list(
            _request("items.list.run", {"status": "done"})
        )
        assert outcome.primary_success
        rows = outcome.result_payload["rows"]
        assert outcome.result_payload["count"] == 1
        assert rows[0]["title"] == "Done thing"
        assert set(rows[0].keys()) == {
            "id", "title", "status", "priority", "type", "source",
        }

    def test_fields_projection_and_limit(self, test_db):
        for n in range(3):
            insert_item(test_db, id=n + 1, title=f"Item {n + 1}")
        test_db.commit()
        outcome = items_listing.handle_items_list(
            _request(
                "items.list.run",
                {"fields": ["id", "title"], "limit": 2},
            )
        )
        assert outcome.primary_success
        rows = outcome.result_payload["rows"]
        assert len(rows) == 2
        assert set(rows[0].keys()) == {"id", "title"}

    def test_project_field_joins_slug(self, test_db):
        insert_item(test_db, id=1, title="Projected", project="yoke")
        test_db.commit()
        outcome = items_listing.handle_items_list(
            _request("items.list.run", {"fields": ["id", "project"]})
        )
        assert outcome.primary_success
        assert outcome.result_payload["rows"][0]["project"] == "yoke"

    def test_rejects_virtual_body_field(self):
        outcome = items_listing.handle_items_list(
            _request("items.list.run", {"fields": ["id", "body"]})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "items.get.run" in outcome.error.message

    def test_rejects_unknown_field(self):
        outcome = items_listing.handle_items_list(
            _request("items.list.run", {"fields": ["definitely_not_a_col"]})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_rejects_out_of_bounds_limit(self):
        outcome = items_listing.handle_items_list(
            _request("items.list.run", {"limit": 0})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_empty_result_is_success_with_zero_count(self, test_db):
        outcome = items_listing.handle_items_list(
            _request("items.list.run", {"status": "done"})
        )
        assert outcome.primary_success
        assert outcome.result_payload["rows"] == []
        assert outcome.result_payload["count"] == 0

    def test_numeric_actor_unscoped_list_sees_only_granted_projects(self, test_db):
        insert_item(test_db, id=1, title="Yoke only", project="yoke")
        insert_item(test_db, id=2, title="Buzz only", project="buzz")
        actor_id = _grant_project_viewer(test_db, "buzz")

        outcome = items_listing.handle_items_list(
            _request(
                "items.list.run",
                {"fields": ["id", "project", "title"]},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == [
            {"id": "2", "project": "buzz", "title": "Buzz only"}
        ]

    def test_numeric_actor_explicit_ungranted_project_sees_zero_rows(self, test_db):
        insert_item(test_db, id=1, title="Yoke only", project="yoke")
        insert_item(test_db, id=2, title="Buzz only", project="buzz")
        actor_id = _grant_project_viewer(test_db, "buzz")

        outcome = items_listing.handle_items_list(
            _request(
                "items.list.run",
                {"fields": ["id"], "project": "yoke"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == []

    def test_numeric_actor_explicit_granted_project_sees_its_rows(self, test_db):
        insert_item(test_db, id=1, title="Yoke only", project="yoke")
        insert_item(test_db, id=2, title="Buzz only", project="buzz")
        actor_id = _grant_project_viewer(test_db, "buzz")

        outcome = items_listing.handle_items_list(
            _request(
                "items.list.run",
                {"fields": ["id", "project"], "project": "buzz"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == [
            {"id": "2", "project": "buzz"}
        ]

    def test_numeric_actor_explicit_duplicate_slug_uses_visible_project(self, test_db):
        _, visible_project = _insert_shared_slug_items(test_db)
        actor_id = _grant_project_viewer_id(test_db, visible_project)

        outcome = items_listing.handle_items_list(
            _request(
                "items.list.run",
                {"fields": ["id", "title"], "project": "shared"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == [
            {"id": "911", "title": "shared zorp other"}
        ]

    def test_numeric_actor_with_no_grants_sees_empty_list(self, test_db):
        insert_item(test_db, id=1, title="Yoke only", project="yoke")
        seed_roles_and_permissions(test_db)
        actor_id = seed_human_actor(test_db)

        outcome = items_listing.handle_items_list(
            _request("items.list.run", {"fields": ["id"]}, actor_id=actor_id)
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == []


class TestItemsSearch:
    def test_matches_title_and_structured_fields(self, test_db):
        insert_item(
            test_db, id=1, title="Wibble feature", spec="nothing here",
        )
        insert_item(
            test_db, id=2, title="Other", spec="mentions wibble deep in spec",
        )
        insert_item(test_db, id=3, title="Unrelated")
        test_db.commit()
        outcome = items_listing.handle_items_search(
            _request("items.search.run", {"keywords": "wibble"})
        )
        assert outcome.primary_success
        matches = outcome.result_payload["matches"]
        assert [m["id"] for m in matches] == [1, 2]
        assert set(matches[0].keys()) == {"id", "title", "status"}

    def test_rejects_empty_keywords(self):
        outcome = items_listing.handle_items_search(
            _request("items.search.run", {"keywords": "  "})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_scopes_to_project_when_given(self, test_db):
        # 13468: search from a project checkout must scope to that project,
        # not leak cross-project matches.
        insert_item(test_db, id=1, title="shared zorp alpha", project="yoke")
        insert_item(test_db, id=2, title="shared zorp beta", project="buzz")
        test_db.commit()
        out_all = items_listing.handle_items_search(
            _request("items.search.run", {"keywords": "zorp"})
        )
        assert [m["id"] for m in out_all.result_payload["matches"]] == [1, 2]
        out_buzz = items_listing.handle_items_search(
            _request("items.search.run", {"keywords": "zorp", "project": "buzz"})
        )
        assert [m["id"] for m in out_buzz.result_payload["matches"]] == [2]

    def test_numeric_actor_unscoped_search_sees_only_granted_projects(self, test_db):
        insert_item(test_db, id=1, title="shared zorp alpha", project="yoke")
        insert_item(test_db, id=2, title="shared zorp beta", project="buzz")
        actor_id = _grant_project_viewer(test_db, "buzz")

        outcome = items_listing.handle_items_search(
            _request("items.search.run", {"keywords": "zorp"}, actor_id=actor_id)
        )

        assert outcome.primary_success
        assert [m["id"] for m in outcome.result_payload["matches"]] == [2]

    def test_numeric_actor_explicit_ungranted_project_sees_zero_matches(
        self, test_db
    ):
        insert_item(test_db, id=1, title="shared zorp alpha", project="yoke")
        insert_item(test_db, id=2, title="shared zorp beta", project="buzz")
        actor_id = _grant_project_viewer(test_db, "buzz")

        outcome = items_listing.handle_items_search(
            _request(
                "items.search.run",
                {"keywords": "zorp", "project": "yoke"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["matches"] == []

    def test_numeric_actor_explicit_granted_project_sees_its_matches(self, test_db):
        insert_item(test_db, id=1, title="shared zorp alpha", project="yoke")
        insert_item(test_db, id=2, title="shared zorp beta", project="buzz")
        actor_id = _grant_project_viewer(test_db, "buzz")

        outcome = items_listing.handle_items_search(
            _request(
                "items.search.run",
                {"keywords": "zorp", "project": "buzz"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert [m["id"] for m in outcome.result_payload["matches"]] == [2]

    def test_numeric_actor_explicit_duplicate_slug_searches_visible_project(
        self, test_db
    ):
        _, visible_project = _insert_shared_slug_items(test_db)
        actor_id = _grant_project_viewer_id(test_db, visible_project)

        outcome = items_listing.handle_items_search(
            _request(
                "items.search.run",
                {"keywords": "zorp", "project": "shared"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert [m["id"] for m in outcome.result_payload["matches"]] == [911]
