"""Tests for the strategy-document body-section renderer.

Covers the shared body-fetch path (``build_body`` / ``query_item`` body)
for linked, unlinked, cross-project, and repeated fetches. The renderer
must not embed document content, infer CURRENT-PLAN, or write the
generated instruction back into stored spec.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import render_body
from yoke_core.domain.items_queries import query_item
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.render_body_strategy import (
    STRATEGY_REFERENCE_HEADING,
    strategy_doc_get_command,
    strategy_reference_instruction,
)
from runtime.api.domain.render_body_test_helpers import (
    _connect,
    _init_db,
    _link_item_strategy,
    _seed_item,
    _seed_strategy_doc,
    _set_field,
)

_YOKE = SEED_PROJECT_IDS["yoke"]
_EXTERNAL = SEED_PROJECT_IDS["externalwebapp"]
_SECRET = "UNIQUE_STRATEGY_BODY_PHRASE"


class TestStrategyReferenceInstruction:
    def test_names_project_slug_and_retrieval_command(self) -> None:
        text = strategy_reference_instruction("yoke", "AREA-PLAN")
        command = strategy_doc_get_command("yoke", "AREA-PLAN")
        assert text.startswith(
            "Before executing this item, read strategy yoke/AREA-PLAN:"
        )
        assert command == "yoke strategy doc get AREA-PLAN --project yoke"
        assert f"`{command}`" in text


class TestBuildBodyStrategyReference:
    def test_unlinked_item_omits_section(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 61, "Unlinked item")
            _seed_strategy_doc(conn, _YOKE, "CURRENT-PLAN", f"# Plan\n{_SECRET}\n")
            _set_field(conn, 61, "spec", "Spec body.")
            body = query_item(61, "body", db_path=db_path)
            spec = query_item(61, "spec", db_path=db_path)
            conn.close()
        assert STRATEGY_REFERENCE_HEADING not in body
        assert "read strategy" not in body
        assert "CURRENT-PLAN" not in body
        assert spec == "Spec body."

    def test_linked_same_project_emits_instruction(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 62, "Linked item")
            _seed_strategy_doc(conn, _YOKE, "AREA-PLAN", f"# Area\n{_SECRET}\n")
            _link_item_strategy(conn, 62, _YOKE, "AREA-PLAN")
            _set_field(conn, 62, "spec", "Spec body.")
            body = query_item(62, "body", db_path=db_path)
            conn.close()
        assert body.startswith(f"{STRATEGY_REFERENCE_HEADING}\n")
        expected = strategy_reference_instruction("yoke", "AREA-PLAN")
        assert expected in body
        assert "Spec body." in body
        assert _SECRET not in body
        assert body.index(expected) < body.index("Spec body.")

    def test_cross_project_link_names_owning_project(self, tmp_path: Path) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 63, "Cross-project item")
            _seed_strategy_doc(
                conn,
                _EXTERNAL,
                "AREA-PLAN",
                f"# External\n{_SECRET}\n",
            )
            _link_item_strategy(conn, 63, _EXTERNAL, "AREA-PLAN")
            _set_field(conn, 63, "spec", "Spec body.")
            body = query_item(63, "body", db_path=db_path)
            conn.close()
        expected = strategy_reference_instruction("externalwebapp", "AREA-PLAN")
        assert expected in body
        assert "yoke/AREA-PLAN" not in body
        assert _SECRET not in body

    def test_repeated_fetch_is_identical_and_does_not_write_spec(
        self,
        tmp_path: Path,
    ) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 64, "Repeat fetch item")
            _seed_strategy_doc(conn, _YOKE, "AREA-PLAN", f"# Area\n{_SECRET}\n")
            _link_item_strategy(conn, 64, _YOKE, "AREA-PLAN")
            _set_field(conn, 64, "spec", "Original spec.")
            first = query_item(64, "body", db_path=db_path)
            second = query_item(64, "body", db_path=db_path)
            spec = query_item(64, "spec", db_path=db_path)
            via_build = render_body.build_body(conn, 64) or ""
            conn.close()
        assert first == second
        assert first == via_build
        assert spec == "Original spec."
        assert "Before executing this item" not in spec
        assert STRATEGY_REFERENCE_HEADING not in spec

    def test_operator_strategy_heading_in_spec_stripped(
        self,
        tmp_path: Path,
    ) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 65, "Dup strategy heading")
            _seed_strategy_doc(conn, _YOKE, "AREA-PLAN", f"# Area\n{_SECRET}\n")
            _link_item_strategy(conn, 65, _YOKE, "AREA-PLAN")
            _set_field(
                conn,
                65,
                "spec",
                "Intro.\n\n## Strategy\n\nOperator copy.\n\n## File Budget\n\n- x.py\n",
            )
            body = query_item(65, "body", db_path=db_path)
            conn.close()
        assert body.count(STRATEGY_REFERENCE_HEADING) == 1
        assert "Operator copy." not in body
        assert "## File Budget" in body
        assert strategy_reference_instruction("yoke", "AREA-PLAN") in body

    def test_linked_item_without_other_content_still_emits(
        self,
        tmp_path: Path,
    ) -> None:
        with _init_db(tmp_path) as db_path:
            conn = _connect(db_path)
            _seed_item(conn, 66, "Linked empty")
            _seed_strategy_doc(conn, _YOKE, "AREA-PLAN", f"# Area\n{_SECRET}\n")
            _link_item_strategy(conn, 66, _YOKE, "AREA-PLAN")
            body = query_item(66, "body", db_path=db_path)
            conn.close()
        assert strategy_reference_instruction("yoke", "AREA-PLAN") in body
        assert _SECRET not in body
