"""Handler coverage for items.search.run."""

from __future__ import annotations

from runtime.api.conftest import insert_item
from runtime.api.domain.handlers.items_read_test_support import (
    grant_project_viewer,
    grant_project_viewer_id,
    insert_prefixed_project,
    insert_shared_slug_items,
    request_for,
)
from yoke_core.domain.handlers import items_search


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
        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "wibble"})
        )
        assert outcome.primary_success
        matches = outcome.result_payload["matches"]
        assert [m["id"] for m in matches] == ["YOK-2", "YOK-1"]
        assert set(matches[0].keys()) == {
            "id", "internal_id", "title", "status", "project", "project_id",
        }

    def test_matches_a_bare_sequence_the_item_text_never_mentions(
        self, test_db,
    ):
        insert_item(
            test_db, id=1, title="Nothing about that number",
            project_sequence=1991,
        )
        insert_item(test_db, id=2, title="Mentions 1991 in its title")
        test_db.commit()

        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "1991"})
        )

        assert outcome.primary_success
        matches = outcome.result_payload["matches"]
        # The referenced item leads, and is reachable at all only through the
        # reference arm — none of its authored text carries the number.
        assert [m["id"] for m in matches] == ["YOK-1991", "YOK-2"]

    def test_matches_a_prefixed_public_ref(self, test_db):
        project_id = insert_prefixed_project(test_db, project_id=120, prefix="ABC")
        insert_item(
            test_db, id=1, title="Nothing about that number",
            project_id=project_id, project_sequence=1991,
        )
        test_db.commit()

        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "ABC-1991"})
        )

        assert outcome.primary_success
        matches = outcome.result_payload["matches"]
        assert [m["id"] for m in matches] == ["ABC-1991"]

    def test_prefixed_ref_ignores_the_same_sequence_in_another_project(
        self, test_db,
    ):
        wanted = insert_prefixed_project(test_db, project_id=120, prefix="ABC")
        other = insert_prefixed_project(test_db, project_id=121, prefix="XYZ")
        insert_item(
            test_db, id=1, title="Wanted", project_id=wanted,
            project_sequence=1991,
        )
        insert_item(
            test_db, id=2, title="Same sequence elsewhere", project_id=other,
            project_sequence=1991,
        )
        test_db.commit()

        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "abc-1991"})
        )

        assert outcome.primary_success
        assert [m["id"] for m in outcome.result_payload["matches"]] == ["ABC-1991"]

    def test_limit_keeps_the_newest_matches(self, test_db):
        for item_id in (1, 2, 3):
            insert_item(test_db, id=item_id, title=f"zorp {item_id}")
        test_db.commit()

        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "zorp", "limit": 2})
        )

        assert outcome.primary_success
        assert [m["id"] for m in outcome.result_payload["matches"]] == ["YOK-3", "YOK-2"]

    def test_rejects_limit_out_of_bounds(self):
        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "zorp", "limit": 0})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_rejects_empty_keywords(self):
        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "  "})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_scopes_to_project_when_given(self, test_db):
        # 13468: search from a project checkout must scope to that project,
        # not leak cross-project matches.
        insert_item(test_db, id=1, title="shared zorp alpha", project="yoke")
        insert_item(test_db, id=2, title="shared zorp beta", project="externalwebapp")
        test_db.commit()
        out_all = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "zorp"})
        )
        assert [m["id"] for m in out_all.result_payload["matches"]] == ["EXT-2", "YOK-1"]
        out_externalwebapp = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "zorp", "project": "externalwebapp"})
        )
        assert [m["id"] for m in out_externalwebapp.result_payload["matches"]] == ["EXT-2"]

    def test_numeric_actor_unscoped_search_sees_only_granted_projects(self, test_db):
        insert_item(test_db, id=1, title="shared zorp alpha", project="yoke")
        insert_item(test_db, id=2, title="shared zorp beta", project="externalwebapp")
        actor_id = grant_project_viewer(test_db, "externalwebapp")

        outcome = items_search.handle_items_search(
            request_for("items.search.run", {"keywords": "zorp"}, actor_id=actor_id)
        )

        assert outcome.primary_success
        assert [m["id"] for m in outcome.result_payload["matches"]] == ["EXT-2"]

    def test_numeric_actor_explicit_ungranted_project_sees_zero_matches(
        self, test_db
    ):
        insert_item(test_db, id=1, title="shared zorp alpha", project="yoke")
        insert_item(test_db, id=2, title="shared zorp beta", project="externalwebapp")
        actor_id = grant_project_viewer(test_db, "externalwebapp")

        outcome = items_search.handle_items_search(
            request_for(
                "items.search.run",
                {"keywords": "zorp", "project": "yoke"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert outcome.result_payload["matches"] == []

    def test_numeric_actor_explicit_granted_project_sees_its_matches(self, test_db):
        insert_item(test_db, id=1, title="shared zorp alpha", project="yoke")
        insert_item(test_db, id=2, title="shared zorp beta", project="externalwebapp")
        actor_id = grant_project_viewer(test_db, "externalwebapp")

        outcome = items_search.handle_items_search(
            request_for(
                "items.search.run",
                {"keywords": "zorp", "project": "externalwebapp"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert [m["id"] for m in outcome.result_payload["matches"]] == ["EXT-2"]

    def test_numeric_actor_explicit_duplicate_slug_searches_visible_project(
        self, test_db
    ):
        _, visible_project = insert_shared_slug_items(test_db)
        actor_id = grant_project_viewer_id(test_db, visible_project)

        outcome = items_search.handle_items_search(
            request_for(
                "items.search.run",
                {"keywords": "zorp", "project": "shared"},
                actor_id=actor_id,
            )
        )

        assert outcome.primary_success
        assert [m["id"] for m in outcome.result_payload["matches"]] == ["OSH-911"]
