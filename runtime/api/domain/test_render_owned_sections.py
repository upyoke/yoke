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

from pathlib import Path

from yoke_core.domain import render_body
from runtime.api.domain.render_body_test_helpers import (
    _connect,
    _init_db,
    _seed_item,
    _set_field,
)


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
                conn,
                32,
                "spec",
                "Intro.\n\n## DB Claim\n\nOperator copy.\n\n## File Budget\n\n- bar.py\n",
            )
            try:
                body = render_body.build_body(conn, 32) or ""
            finally:
                conn.close()
            assert "Operator copy." not in body
            # File Budget survives as operator-authored content.
            assert "## File Budget" in body
