"""Structured-write (file/stdin) tests for ``yoke_core.domain.backlog``.

Shared fixtures and seed helpers are imported from ``test_backlog``. Frozen
attestation immutability tests live in ``test_backlog_queries_freeze.py``.
"""

from __future__ import annotations

import io
import os
import tempfile
from unittest import mock

from yoke_core.domain import backlog
from runtime.api.test_backlog import (
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — re-exported fixture
)


class TestExecuteStructuredWrite:
    def test_basic_structured_write(self, tmp_db):
        _seed_item(tmp_db, id=10)
        out = io.StringIO()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Spec content\n\nSome spec details.\n")
            f.flush()
            spec_path = f.name

        try:
            with _patch_externals(), \
                 mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
                result = backlog.execute_structured_write(
                    item_id=10,
                    field="spec",
                    file_path=spec_path,
                    out=out,
                )
        finally:
            os.unlink(spec_path)

        assert result["success"] is True
        assert "Spec content" in _item_field(tmp_db, 10, "spec")

    def test_invalid_field_rejected(self):
        out = io.StringIO()
        result = backlog.execute_structured_write(
            item_id=10,
            field="bogus",
            file_path="/nonexistent",
            out=out,
        )
        assert result["success"] is False
        assert "invalid structured field" in result["error"]

    def test_missing_file_rejected(self):
        out = io.StringIO()
        result = backlog.execute_structured_write(
            item_id=10,
            field="spec",
            file_path="/nonexistent/file.md",
            out=out,
        )
        assert result["success"] is False
        assert "file not found" in result["error"]

    def test_shrinkage_guard(self, tmp_db):
        existing_spec = "\n".join([f"Line {i}" for i in range(20)])
        _seed_item(tmp_db, id=10, spec=existing_spec)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("Short\nspec\ncontent\n")
            f.flush()
            spec_path = f.name

        out = io.StringIO()
        try:
            with _patch_externals(), \
                 mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
                result = backlog.execute_structured_write(
                    item_id=10,
                    field="spec",
                    file_path=spec_path,
                    out=out,
                )
        finally:
            os.unlink(spec_path)

        assert result["success"] is False
        assert "content loss" in result["error"]

    def test_shrinkage_guard_force_override(self, tmp_db):
        existing_spec = "\n".join([f"Line {i}" for i in range(20)])
        _seed_item(tmp_db, id=10, spec=existing_spec)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("Short\nspec\ncontent\n")
            f.flush()
            spec_path = f.name

        out = io.StringIO()
        try:
            with _patch_externals(), \
                 mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
                result = backlog.execute_structured_write(
                    item_id=10,
                    field="spec",
                    file_path=spec_path,
                    force=True,
                    out=out,
                )
        finally:
            os.unlink(spec_path)

        assert result["success"] is True

    def test_empty_content_guard(self, tmp_db):
        _seed_item(tmp_db, id=10, spec="# Existing spec\n\nWith content.\n")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("")
            f.flush()
            spec_path = f.name

        out = io.StringIO()
        try:
            with _patch_externals(), \
                 mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
                result = backlog.execute_structured_write(
                    item_id=10,
                    field="spec",
                    file_path=spec_path,
                    out=out,
                )
        finally:
            os.unlink(spec_path)

        assert result["success"] is False
        assert "empty" in result["error"]

    def test_spec_updated_by_tracking(self, tmp_db):
        _seed_item(tmp_db, id=10)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# New spec\n\nContent here.\n")
            f.flush()
            spec_path = f.name

        out = io.StringIO()
        try:
            with _patch_externals(), \
                 mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
                result = backlog.execute_structured_write(
                    item_id=10,
                    field="spec",
                    file_path=spec_path,
                    source="engineer",
                    out=out,
                )
        finally:
            os.unlink(spec_path)

        assert result["success"] is True
        assert _item_field(tmp_db, 10, "spec_updated_by") == "engineer"

    def test_stdin_content_path(self, tmp_db):
        """AC-1/AC-2: content param bypasses file reading, same pipeline."""
        _seed_item(tmp_db, id=10)
        out = io.StringIO()

        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="spec",
                content="# Stdin spec\n\nFrom stdin.\n",
                out=out,
            )

        assert result["success"] is True
        assert "Stdin spec" in _item_field(tmp_db, 10, "spec")
        assert "stdin" in out.getvalue()

    def test_mutual_exclusion_both_provided(self):
        """AC-4: both content and file_path → error."""
        out = io.StringIO()
        result = backlog.execute_structured_write(
            item_id=10,
            field="spec",
            file_path="/some/file",
            content="some content",
            out=out,
        )
        assert result["success"] is False
        assert "cannot use both" in result["error"]

    def test_neither_provided(self):
        """AC-4: neither content nor file_path → error."""
        out = io.StringIO()
        result = backlog.execute_structured_write(
            item_id=10,
            field="spec",
            out=out,
        )
        assert result["success"] is False
        assert "requires" in result["error"]

    def test_stdin_empty_content_guard(self, tmp_db):
        """AC-6: empty-content guard fires for stdin path."""
        _seed_item(tmp_db, id=10, spec="# Existing spec\n\nWith content.\n")
        out = io.StringIO()

        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="spec",
                content="",
                out=out,
            )

        assert result["success"] is False
        assert "empty" in result["error"]

    def test_stdin_shrinkage_guard(self, tmp_db):
        """AC-6: shrinkage guard fires for stdin path."""
        existing_spec = "\n".join([f"Line {i}" for i in range(20)])
        _seed_item(tmp_db, id=10, spec=existing_spec)
        out = io.StringIO()

        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="spec",
                content="Short\nspec\n",
                out=out,
            )

        assert result["success"] is False
        assert "content loss" in result["error"]

    def test_structured_write_rebuilds_board_even_in_global_dry_run(self, tmp_db):
        _seed_item(tmp_db, id=10)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# New spec\n\nContent here.\n")
            f.flush()
            spec_path = f.name

        out = io.StringIO()
        try:
            with _patch_externals() as patched, \
                 mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}), \
                 mock.patch("yoke_core.domain.backlog_updates._is_dry_run", return_value=True):
                result = backlog.execute_structured_write(
                    item_id=10,
                    field="spec",
                    file_path=spec_path,
                    out=out,
                )
        finally:
            os.unlink(spec_path)

        assert result["success"] is True
        patched["_rebuild_board"].assert_called_once_with(out)
