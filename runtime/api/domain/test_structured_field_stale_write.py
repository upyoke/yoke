"""Compare-and-write concurrency and guard coverage on disposable Postgres."""

import io
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from runtime.api.domain.test_backlog_structured_write_api import _FakeDB, _patched_db
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import backlog_structured_write_op as writes


class TestExpectedContent(unittest.TestCase):
    def setUp(self):
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(101, spec=None)

    def write(self, content, expected):
        return writes.execute_structured_write(
            item_id=101,
            field="spec",
            content=content,
            expected_content=expected,
            out=io.StringIO(),
        )

    def test_null_is_empty_and_unchanged_is_noop(self):
        self.assertTrue(self.write("first", "")["success"])
        self.assertFalse(self.write("first", "first")["changed"])
        stale = self.write("second", "")
        self.assertFalse(stale["success"])
        self.assertIn("structured_field_stale:", stale["error"])
        self.assertEqual(self.db.fetch_field(101, "spec"), "first")

    def test_row_lock_waits_then_refuses_stale_without_side_effects(self):
        attempted = threading.Event()
        real_connect = writes.connect

        class Connection:
            def __init__(self):
                self.inner = real_connect(self_db.path)

            def execute(self, sql, params=()):
                if "FOR UPDATE" in sql:
                    attempted.set()
                return self.inner.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self.inner, name)

        self_db = self.db
        with connect_test_db(self.db.path) as winner:
            winner.execute("SELECT id FROM items WHERE id=%s FOR UPDATE", (101,))
            winner.execute("UPDATE items SET spec=%s WHERE id=%s", ("winner", 101))
            with ThreadPoolExecutor(max_workers=1) as pool:
                with mock.patch.object(
                    writes, "connect", side_effect=lambda _: Connection()
                ):
                    future = pool.submit(self.write, "loser", "")
                    self.assertTrue(
                        attempted.wait(5), "writer never reached the row lock"
                    )
                    self.assertFalse(
                        future.done(), "writer did not wait for the row lock"
                    )
                    winner.commit()
                    result = future.result(timeout=5)
        self.assertFalse(result["success"])
        self.assertIn("structured_field_stale:", result["error"])
        self.assertEqual(self.db.fetch_field(101, "spec"), "winner")

    def test_expected_content_keeps_empty_and_shrinkage_guards(self):
        existing = "line\n" * 12
        self.assertTrue(self.write(existing, "")["success"])
        self.assertFalse(self.write("", existing)["success"])
        self.assertIn("less than 50%", self.write("short", existing)["error"])
        self.assertEqual(self.db.fetch_field(101, "spec"), existing)
