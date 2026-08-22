"""Handler coverage for items.list.run."""

from __future__ import annotations

from runtime.api.conftest import insert_item
from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_human_actor
from runtime.api.domain.handlers.items_read_test_support import (
    grant_project_viewer,
    grant_project_viewer_id,
    insert_shared_slug_items,
    request_for,
)
from yoke_core.domain.handlers import items_listing


class TestItemsList:
    def test_filters_by_status_with_default_fields(self, test_db):
        insert_item(test_db, id=1, title="Done thing", status="done")
        insert_item(test_db, id=2, title="Open thing", status="idea")
        test_db.commit()
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {"status": "done"})
        )
        assert outcome.primary_success
        rows = outcome.result_payload["rows"]
        assert outcome.result_payload["count"] == 1
        assert rows[0]["title"] == "Done thing"
        assert set(rows[0].keys()) == {
            "id", "title", "status", "priority", "workflow_id", "source",
        }

    def test_fields_projection_and_limit(self, test_db):
        for n in range(3):
            insert_item(test_db, id=n + 1, title=f"Item {n + 1}")
        test_db.commit()
        outcome = items_listing.handle_items_list(
            request_for(
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
            request_for("items.list.run", {"fields": ["id", "project"]})
        )
        assert outcome.primary_success
        assert outcome.result_payload["rows"][0]["project"] == "yoke"

    def test_rejects_virtual_body_field(self):
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {"fields": ["id", "body"]})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "items.get.run" in outcome.error.message

    def test_rejects_unknown_field(self):
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {"fields": ["definitely_not_a_col"]})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_rejects_out_of_bounds_limit(self):
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {"limit": 0})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_empty_result_is_success_with_zero_count(self, test_db):
        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {"status": "done"})
        )
        assert outcome.primary_success
        assert outcome.result_payload["rows"] == []
        assert outcome.result_payload["count"] == 0

    def test_numeric_actor_unscoped_list_sees_only_granted_projects(self, test_db):
        insert_item(test_db, id=1, title="Yoke only", project="yoke")
        insert_item(test_db, id=2, title="ExternalWebapp only", project="externalwebapp")
        actor_id = grant_project_viewer(test_db, "externalwebapp")

        outcome = items_listing.handle_items_list(
            request_for(
                "items.list.run",
                {"fields": ["id", "project", "title"]},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == [
            {"id": "EXT-2", "project": "externalwebapp", "title": "ExternalWebapp only"}
        ]

    def test_numeric_actor_explicit_ungranted_project_sees_zero_rows(self, test_db):
        insert_item(test_db, id=1, title="Yoke only", project="yoke")
        insert_item(test_db, id=2, title="ExternalWebapp only", project="externalwebapp")
        actor_id = grant_project_viewer(test_db, "externalwebapp")

        outcome = items_listing.handle_items_list(
            request_for(
                "items.list.run",
                {"fields": ["id"], "project": "yoke"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == []

    def test_numeric_actor_explicit_granted_project_sees_its_rows(self, test_db):
        insert_item(test_db, id=1, title="Yoke only", project="yoke")
        insert_item(test_db, id=2, title="ExternalWebapp only", project="externalwebapp")
        actor_id = grant_project_viewer(test_db, "externalwebapp")

        outcome = items_listing.handle_items_list(
            request_for(
                "items.list.run",
                {"fields": ["id", "project"], "project": "externalwebapp"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == [
            {"id": "EXT-2", "project": "externalwebapp"}
        ]

    def test_numeric_actor_explicit_duplicate_slug_uses_visible_project(self, test_db):
        _, visible_project = insert_shared_slug_items(test_db)
        actor_id = grant_project_viewer_id(test_db, visible_project)

        outcome = items_listing.handle_items_list(
            request_for(
                "items.list.run",
                {"fields": ["id", "title"], "project": "shared"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == [
            {"id": "OSH-911", "title": "shared zorp other"}
        ]

    def test_numeric_actor_with_no_grants_sees_empty_list(self, test_db):
        insert_item(test_db, id=1, title="Yoke only", project="yoke")
        seed_roles_and_permissions(test_db)
        actor_id = seed_human_actor(test_db)

        outcome = items_listing.handle_items_list(
            request_for("items.list.run", {"fields": ["id"]}, actor_id=actor_id)
        )

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == []
