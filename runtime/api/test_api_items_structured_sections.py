"""Regression checks for api items structured sections."""

from __future__ import annotations

from runtime.api.test_api_items_structured import (
    _ApiSuite as _ApiSuite,
    _envelope as _envelope,
    apply_fixture_ddl as apply_fixture_ddl,
    connect_test_db as connect_test_db,
    init_test_db as init_test_db,
)


class TestStructuredFieldAppendAddendumRoute(_ApiSuite):
    def test_append_addendum_happy_path(self) -> None:
        self.db.insert_item(101, spec="# Spec\n\nbody\n")
        env = _envelope(
            "items.structured_field.append_addendum",
            payload={
                "field": "spec",
                "heading": "Refinement Addendum",
                "content": "more",
            },
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertTrue(body["result"]["changed"])
        self.assertIn("## Refinement Addendum", self.db.fetch_field(101, "spec"))

    def test_append_addendum_empty_rejected(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.structured_field.append_addendum",
            payload={"field": "spec", "heading": "X", "content": ""},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        # The domain owner's "refusing addendum with empty content" maps
        # through _classify_write_error → "empty_body" → HTTP 422.
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "empty_body")


class TestStructuredFieldSectionRoutes(_ApiSuite):
    def test_section_upsert_writes_section_row(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.structured_field.section_upsert",
            payload={"section": "Notes", "content": "note body\n"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"]["section"], "Notes")
        self.assertNotIn("field", body["result"])
        self.assertNotIn("heading_level", body["result"])

    def test_section_append_writes_entry(self) -> None:
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.structured_field.section_append",
            payload={
                "section": "Progress Log",
                "headline": "checkpoint",
                "content": "body",
            },
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])


class TestProgressLogAppendRoute(_ApiSuite):
    def test_progress_log_append_happy_path(self) -> None:
        """Append into 'Progress Log' with ordering=200."""
        self.db.insert_item(101, spec="x\n")
        env = _envelope(
            "items.progress_log.append",
            payload={"headline": "checkpoint", "content": "body"},
        )
        resp = self.client.post("/v1/functions/call", json=env)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["result"]["section"], "Progress Log")


class TestFieldTargetedSectionRoute(_ApiSuite):
    def test_field_receipt_and_default_depth(self):
        self.db.insert_item(101, spec="")
        env = _envelope(
            "items.structured_field.section_upsert",
            payload={
                "field": "spec",
                "section": "EDGE",
                "content": "body",
            },
        )
        body = self.client.post("/v1/functions/call", json=env).json()
        self.assertTrue(body["success"], body)
        self.assertEqual(body["result"]["field"], "spec")
        self.assertEqual(body["result"]["heading_level"], 2)
        self.assertEqual(self.db.fetch_field(101, "spec"), "## EDGE\n\nbody\n")

    def test_invalid_payloads_do_not_write(self):
        self.db.insert_item(101, spec="original")
        invalid = [
            {"field": "unknown"},
            {"heading_level": 1},
            {"heading_level": 7},
            {"ordering": 5},
            {"section": "two\nlines"},
            {"section": ""},
            {"content": " "},
            {"unexpected": True},
        ]
        for change in invalid:
            with self.subTest(change=change):
                payload = {"field": "spec", "section": "EDGE", "content": "body"}
                payload.update(change)
                body = self.client.post(
                    "/v1/functions/call",
                    json=_envelope(
                        "items.structured_field.section_upsert",
                        payload=payload,
                    ),
                ).json()
                self.assertFalse(body["success"], body)
                self.assertEqual(self.db.fetch_field(101, "spec"), "original")
