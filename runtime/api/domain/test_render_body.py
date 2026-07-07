"""Tests for render_body — pure render helper.

After the body-retirement, render_body is a pure function: it reads structured
fields and renders a body string. There are no DB writes, no body column, no
body_generated_at, no backlog .md generation, no GitHub sync.

The original module covered every flavor of rendering. It is now split across
sibling files so each authored file stays under the 350-line limit. The
TC-render-body-* shell-backstop suite lives in
``test_render_body_shell_backstop`` and the unified ``## DB Claim`` body
section coverage lives in ``test_render_body_db_claim``. Heavy fixture/helper
code lives in ``render_body_test_helpers``.
"""

from __future__ import annotations

import io
from pathlib import Path

from yoke_core.domain import render_body
from yoke_core.domain.render_body_test_helpers import (
    _connect,
    _init_db,
    _p,
    _seed_item,
    _set_field,
)


class TestBrowserQaMetadataInvisibleInBody:
    def test_browser_qa_metadata_not_rendered_into_body(self, tmp_path: Path) -> None:
        """browser_qa_metadata is intentionally excluded from the body renderer.

        Metadata must stay internal — operators scrolling items get YOK-N body
        must never see the raw JSON. Only spec/design/plan/etc. surfaces.
        """
        from yoke_core.domain.browser_qa_metadata import NEGATIVE_DEFAULT_JSON

        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 9, "Invisible metadata test")
            _set_field(conn, 9, "browser_qa_metadata", NEGATIVE_DEFAULT_JSON)
            _set_field(conn, 9, "spec", "# Spec\nVisible spec content.")
            try:
                body = render_body.build_body(conn, 9) or ""
            finally:
                conn.close()
            assert "Visible spec content." in body
            assert "browser_qa_metadata" not in body
            assert "browser_testable" not in body


class TestBuildBody:
    def test_orders_sections_and_strips_duplicate_headings(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            item_id = 7
            _seed_item(conn, item_id, "Render item")
            p = _p(conn)
            conn.execute(
                f"""
                UPDATE items
                SET spec = {p}, design_spec = {p}, technical_plan = {p}, shepherd_caveats = {p}, test_results = {p}
                WHERE id = {p}
                """,
                (
                    "# Render item\n\nIntro paragraph.",
                    "## Design Spec\n\nDesign body.",
                    "## Technical Plan\n\nPlan body.",
                    "Caveat body.",
                    "Results body.",
                    item_id,
                ),
            )
            conn.execute(
                f"""
                INSERT INTO item_sections (item_id, section_name, content, ordering, source, created_at, updated_at)
                VALUES ({p}, 'Absorbed 99', 'Absorbed content.', 100, 'operator', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """,
                (item_id,),
            )
            shepherd_item = f"YOK-{item_id}"
            conn.execute(
                f"""
                INSERT INTO shepherd_verdicts (item, transition, worker, verdict, caveats, attempt, created_at)
                VALUES ({p}, 'review', 'tester', 'PASS', NULL, 1, '2026-01-01T00:00:00Z')
                """,
                (shepherd_item,),
            )
            conn.commit()

            body = render_body.build_body(conn, item_id)
            conn.close()

            assert body is not None
            assert body.startswith("# Spec: Render item\n\nIntro paragraph.")
            assert sum(1 for line in body.splitlines() if line.startswith("# ")) == 1
            assert "## Design Spec\n\nDesign body." in body
            assert "## Technical Plan\n\nPlan body." in body
            assert "## Absorbed 99\n\nAbsorbed content." in body
            assert "## Shepherd Log" in body
            assert "## Test Results\n\nResults body." in body
            assert body.index("Intro paragraph.") < body.index("Design body.")
            assert body.index("Design body.") < body.index("Plan body.")
            assert body.index("Plan body.") < body.index("Absorbed content.")
            assert body.endswith("\n")


class TestRenderItem:
    def test_output_file_for_empty_item(self, tmp_path: Path) -> None:
        """Item with no structured fields renders to empty string."""
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 8, "Empty item")
            conn.close()

            output_file = tmp_path / "body.md"
            rc = render_body.render_item(8, db_path=db_path, output_file=str(output_file))

            assert rc == 0
            assert output_file.read_text(encoding="utf-8") == ""

    def test_epic_progress_notes_render_into_epic_body(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 12, "Epic item")
            conn.execute("UPDATE items SET type = 'epic' WHERE id = 12")
            conn.execute(
                "INSERT INTO epic_tasks (epic_id, task_num, title, status) VALUES (12, 1, 'Task one', 'implementing')"
            )
            conn.execute(
                """INSERT INTO epic_progress_notes
                   (epic_id, task_num, note_num, body, commit_hash, synced_to_github, created_at)
                   VALUES (12, 1, 1, 'Progress body', 'abc123', 0, '2026-01-01T00:00:00Z')"""
            )
            conn.commit()

            body = render_body.build_body(conn, 12) or ""
            conn.close()

            assert "## Epic Progress Notes" in body
            assert "### Task 1 note 1: Task one" in body
            assert "- commit_hash: abc123" in body
            assert "- synced_to_github: 0" in body
            assert "Progress body" in body

    def test_render_is_pure_no_db_writes(self, tmp_path: Path) -> None:
        """Rendering does not write to DB — purely reads and returns."""
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 9, "Pure render item")
            _set_field(conn, 9, "spec", "Spec content for purity test.")
            updated_at_before = conn.execute(
                "SELECT updated_at FROM items WHERE id = 9"
            ).fetchone()[0]
            conn.close()

            out = io.StringIO()
            rc = render_body.render_item(9, db_path=db_path, out=out)
            assert rc == 0
            assert "Spec content for purity test." in out.getvalue()

            # Verify DB was not modified
            conn = _connect(db_path)
            updated_at_after = conn.execute(
                "SELECT updated_at FROM items WHERE id = 9"
            ).fetchone()[0]
            conn.close()
            assert updated_at_before == updated_at_after

    def test_render_immediately_fresh_after_field_update(self, tmp_path: Path) -> None:
        """AC-15: rendered body is immediately fresh after structured-field update."""
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 11, "Fresh render item")
            _set_field(conn, 11, "spec", "Version 1 content")

            body_v1 = render_body.build_body(conn, 11)
            assert body_v1 is not None
            assert "Version 1 content" in body_v1

            _set_field(conn, 11, "spec", "Version 2 content")
            body_v2 = render_body.build_body(conn, 11)
            assert body_v2 is not None
            assert "Version 2 content" in body_v2
            assert "Version 1 content" not in body_v2
            conn.close()


class TestMainEntrypoint:
    """Cover the ``main()`` CLI argument parser surface directly."""

    def test_main_requires_item_id(self) -> None:
        rc = render_body.main([])
        assert rc == 1

    def test_main_rejects_non_numeric_item_id(self) -> None:
        rc = render_body.main(["not-a-number"])
        assert rc == 1

    def test_main_rejects_unknown_flag(self) -> None:
        rc = render_body.main(["1", "--bogus"])
        assert rc == 1

    def test_main_requires_output_file_value(self) -> None:
        rc = render_body.main(["1", "--output-file"])
        assert rc == 1

    def test_main_requires_section_value(self) -> None:
        rc = render_body.main(["1", "--section"])
        assert rc == 1


class TestRenderSection:
    """``render_section`` returns the named ``## <heading>`` block only."""

    def test_section_present_returns_block_only(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 21, "Section item")
            spec_body = (
                "## File Budget\n\nBudget content for item 21.\n\n"
                "## Verification\n\nVerify content.\n"
            )
            _set_field(conn, 21, "spec", spec_body)
            conn.close()

            out = io.StringIO()
            rc = render_body.render_section(
                21, "## File Budget", db_path=db_path, out=out,
            )
            assert rc == 0
            result = out.getvalue()
            assert "Budget content for item 21." in result
            assert "Verification" not in result
            assert "Verify content." not in result

    def test_section_missing_returns_zero_with_advisory(self, tmp_path: Path) -> None:
        """Section absence is normal data, not error — exit 0 keeps
        parallel-batch siblings alive while the advisory still
        distinguishes "section omitted" from "section had no body."
        """
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 22, "No section item")
            _set_field(conn, 22, "spec", "Some spec content without that heading.")
            conn.close()

            out = io.StringIO()
            err = io.StringIO()
            rc = render_body.render_section(
                22, "## File Budget", db_path=db_path, out=out, err=err,
            )
            assert rc == 0
            assert "File Budget" in err.getvalue()
            assert "Advisory" in err.getvalue()
            assert out.getvalue() == ""

    def test_item_missing_still_returns_nonzero(self, tmp_path: Path) -> None:
        """Item-id-not-found stays a real error (exit 1) — the
        exit-0 contract only covers section absence on a real item.
        """
        with _init_db(tmp_path) as db_path:
            out = io.StringIO()
            err = io.StringIO()
            rc = render_body.render_section(
                99999, "## File Budget", db_path=db_path, out=out, err=err,
            )
            assert rc == 1
            assert out.getvalue() == ""

    def test_main_section_flag_threads_through(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 23, "Flag thread item")
            _set_field(
                conn, 23, "spec",
                "## File Budget\n\nBudget body.\n\n## Other\n\nOther.\n",
            )
            conn.close()

            # Drive the CLI argument parser, but route through an isolated
            # YOKE_DB so the test does not require a side-effect-mocked
            # connect path.
            import os as _os
            from unittest import mock as _mock
            with _mock.patch.dict(_os.environ, {"YOKE_DB": db_path}):
                rc = render_body.main(["23", "--section", "## File Budget"])
            assert rc == 0


class TestRendererOwnedSectionStrip:
    """Operator-authored ``## Path Claims`` in spec must not duplicate
    the DB-backed renderer's authoritative version.
    """

    def test_operator_path_claims_in_spec_stripped(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 31, "Path Claims dup item")
            spec_with_dup = (
                "Body intro.\n\n"
                "## File Budget\n\n"
                "- foo.py\n\n"
                "## Path Claims\n\n"
                "Operator-authored planning claim that duplicates DB state.\n\n"
                "- `runtime/api/domain/foo.py`\n\n"
                "## Non-Goals\n\n"
                "Trailing section after the stripped block.\n"
            )
            _set_field(conn, 31, "spec", spec_with_dup)
            try:
                body = render_body.build_body(conn, 31) or ""
            finally:
                conn.close()
            # Trailing section preserved verbatim.
            assert "## Non-Goals" in body
            assert "Trailing section after the stripped block." in body
            # File Budget heading (operator-owned) preserved.
            assert "## File Budget" in body
            # Operator-authored Path Claims block body stripped — only
            # zero or one ``## Path Claims`` heading may remain (zero
            # when no DB claim exists for the test item).
            assert body.count("## Path Claims") <= 1
            assert "Operator-authored planning claim" not in body

    def test_db_claim_heading_in_spec_stripped(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 32, "DB Claim dup item")
            _set_field(
                conn, 32, "spec",
                "Intro.\n\n## DB Claim\n\nOperator copy.\n\n## File Budget\n\n- bar.py\n",
            )
            try:
                body = render_body.build_body(conn, 32) or ""
            finally:
                conn.close()
            assert "Operator copy." not in body
            # File Budget survives as operator-authored content.
            assert "## File Budget" in body
