"""render_body — TC-render-body-* behavioral backstop suite.

Split out of ``test_render_body.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import render_body
from yoke_core.domain.render_body_test_helpers import (
    _connect,
    db_path,  # noqa: F401  (pytest fixture)
    _p,
    _seed_item,
    _set_field,
)


class TestBuildBodyShellBackstop:
    """Behavioral backstop for the retired shell test-render-body suite."""

    def test_tc_render_body_empty_item(self, tmp_path: Path, db_path: str) -> None:
        """TC-render-body-empty-item: item with all fields NULL yields empty body."""
        conn = _connect(db_path)
        _seed_item(conn, 1, "Empty item")
        out_file = tmp_path / "empty.md"
        rc = render_body.render_item(1, db_path=db_path, output_file=str(out_file))
        conn.close()
        assert rc == 0
        assert out_file.read_text(encoding="utf-8") == ""

    def test_tc_render_body_spec_only(self, tmp_path: Path, db_path: str) -> None:
        """TC-render-body-spec-only: spec heading + embedded h2 sections rendered."""
        conn = _connect(db_path)
        _seed_item(conn, 2, "Spec item")
        _set_field(
            conn, 2, "spec",
            "This is the spec content.\n\n"
            "## Problem\nSomething is wrong.\n\n"
            "## Solution\nFix it.",
        )
        out_file = tmp_path / "spec.md"
        rc = render_body.render_item(2, db_path=db_path, output_file=str(out_file))
        conn.close()
        assert rc == 0
        body = out_file.read_text(encoding="utf-8")
        assert "# Spec: Spec item" in body
        assert "This is the spec content." in body
        assert "## Problem" in body
        assert "## Solution" in body

    def test_tc_render_body_all_structured_fields(self, tmp_path: Path, db_path: str) -> None:
        """TC-render-body-all-structured-fields: every structured field surfaces."""
        conn = _connect(db_path)
        _seed_item(conn, 3, "All fields item")
        _set_field(conn, 3, "spec", "Spec content here")
        _set_field(conn, 3, "design_spec", "Design spec content")
        _set_field(conn, 3, "technical_plan", "Technical plan content")
        _set_field(conn, 3, "worktree_plan", "Worktree plan content")
        _set_field(conn, 3, "shepherd_caveats", "Shepherd caveats content")
        _set_field(conn, 3, "test_results", "Test results content")
        _set_field(conn, 3, "deploy_log", "Deploy log content")

        body = render_body.build_body(conn, 3)
        conn.close()
        assert body is not None
        for heading in (
            "# Spec: All fields item",
            "## Design Spec",
            "## Technical Plan",
            "## Worktree Plan",
            "## Shepherd Caveats",
            "## Test Results",
            "## Deploy Log",
        ):
            assert heading in body, f"missing heading: {heading}"

    def test_tc_render_body_item_sections(self, tmp_path: Path, db_path: str) -> None:
        """TC-render-body-item-sections: item_sections ordering < 500 rendered after structured fields."""
        conn = _connect(db_path)
        _seed_item(conn, 4, "Sections item")
        _set_field(conn, 4, "spec", "Base spec")
        absorbed_id = 99
        absorbed_section = f"Absorbed YOK-{absorbed_id}"
        absorbed_content = f"Absorbed content from YOK-{absorbed_id}"
        p = _p(conn)
        conn.execute(
            f"""
            INSERT INTO item_sections (item_id, section_name, content, ordering, source, created_at, updated_at)
            VALUES (4, {p}, {p}, 100, 'operator', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """,
            (absorbed_section, absorbed_content),
        )
        conn.commit()
        body = render_body.build_body(conn, 4)
        conn.close()
        assert body is not None
        assert f"## {absorbed_section}" in body
        assert absorbed_content in body

    def test_tc_render_body_idempotent(self, tmp_path: Path, db_path: str) -> None:
        """TC-render-body-idempotent: render twice, output bytes identical."""
        conn = _connect(db_path)
        _seed_item(conn, 5, "Idempotent item")
        _set_field(conn, 5, "spec", "Idempotent spec content")
        _set_field(conn, 5, "technical_plan", "Idempotent tech plan")
        conn.close()

        out1 = tmp_path / "out1.md"
        out2 = tmp_path / "out2.md"
        rc1 = render_body.render_item(5, db_path=db_path, output_file=str(out1))
        rc2 = render_body.render_item(5, db_path=db_path, output_file=str(out2))
        assert rc1 == 0 and rc2 == 0
        assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")

    def test_tc_render_body_section_ordering(self, tmp_path: Path, db_path: str) -> None:
        """TC-render-body-section-ordering: spec < design < tech < worktree < caveats < test < deploy."""
        conn = _connect(db_path)
        _seed_item(conn, 6, "Ordering item")
        markers = [
            ("spec", "SPEC_MARKER"),
            ("design_spec", "DESIGN_MARKER"),
            ("technical_plan", "TECHPLAN_MARKER"),
            ("worktree_plan", "WORKTREE_MARKER"),
            ("shepherd_caveats", "CAVEATS_MARKER"),
            ("test_results", "TESTRESULTS_MARKER"),
            ("deploy_log", "DEPLOYLOG_MARKER"),
        ]
        for field, value in markers:
            _set_field(conn, 6, field, value)
        body = render_body.build_body(conn, 6)
        conn.close()
        assert body is not None
        positions = [body.index(value) for _, value in markers]
        assert positions == sorted(positions), (
            f"ordering violated: {positions}"
        )

    def test_tc_render_body_duplicate_heading_strip(self, tmp_path: Path, db_path: str) -> None:
        """TC-render-body-duplicate-heading-strip: leading duplicate heading stripped."""
        conn = _connect(db_path)
        item_id = 16
        _seed_item(conn, item_id, "Duplicate heading item")
        _set_field(
            conn, item_id, "technical_plan",
            "## Technical Plan\n\n### Approach\nKeep the heading only once.\n",
        )
        worktree_line = f"YOK-{item_id} in its own worktree"
        _set_field(
            conn, item_id, "worktree_plan",
            f"## Worktree Plan\n\n- {worktree_line}\n",
        )
        body = render_body.build_body(conn, item_id)
        conn.close()
        assert body is not None
        lines = body.splitlines()
        assert lines.count("## Technical Plan") == 1
        assert lines.count("## Worktree Plan") == 1
        assert "### Approach" in body
        assert worktree_line in body

    def test_tc_render_body_spec_leading_h1_strip(self, tmp_path: Path, db_path: str) -> None:
        """TC-render-body-spec-leading-h1-strip: leading H1 inside spec stripped once."""
        conn = _connect(db_path)
        _seed_item(conn, 160, "Spec title strip item")
        _set_field(
            conn, 160, "spec",
            "# Spec title strip item\n\n"
            "Intro paragraph survives below the rendered title.\n\n"
            "## Scope\nNo duplicate H1 should remain.\n",
        )
        body = render_body.build_body(conn, 160)
        conn.close()
        assert body is not None
        h1_count = sum(1 for line in body.splitlines() if line.startswith("# "))
        assert h1_count == 1
        assert "# Spec: Spec title strip item" in body
        assert "Intro paragraph survives below the rendered title." in body
        assert "## Scope" in body
