"""Tests for yoke_core.domain.designs."""
from __future__ import annotations

import os
import tempfile


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestDesigns:
    def test_init_creates_table(self, test_db):
        from yoke_core.domain.designs import cmd_init
        cmd_init(test_db)

    def test_upsert_and_get(self, test_db):
        from yoke_core.domain.designs import cmd_upsert, cmd_get, cmd_get_body
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Design\nContent here")
            f.flush()
            result = cmd_upsert(test_db, TEST_ITEM_ID, "my-design", f.name)
        os.unlink(f.name)
        assert TEST_ITEM_REF in result

        row = cmd_get(test_db, TEST_ITEM_ID)
        assert str(TEST_ITEM_ID) in row
        assert "my-design" in row

        body = cmd_get_body(test_db, TEST_ITEM_ID)
        assert "Content here" in body

    def test_exists(self, test_db):
        from yoke_core.domain.designs import cmd_exists, cmd_upsert
        assert cmd_exists(test_db, 99) is False
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("body")
            f.flush()
            cmd_upsert(test_db, 99, "slug", f.name)
        os.unlink(f.name)
        assert cmd_exists(test_db, 99) is True

    def test_list(self, test_db):
        from yoke_core.domain.designs import cmd_list, cmd_upsert
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("body-one")
            f.flush()
            cmd_upsert(test_db, 1, "s1", f.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("body-two")
            f.flush()
            cmd_upsert(test_db, 2, "s2", f.name)
        result = cmd_list(test_db)
        assert "s1" in result
        assert "s2" in result
