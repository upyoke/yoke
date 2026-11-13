"""A new project receives shipped board defaults and the birth instruction."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.board.config import BoardConfig
from yoke_core.domain.project_policy_capabilities import load_project_policy_settings
from yoke_core.domain.projects_crud import cmd_create
from yoke_core.domain.shipped_execution_instruction import (
    SHIPPED_EXECUTION_INSTRUCTION,
    SHIPPED_WORKFLOW_IDS,
    seed_shipped_execution_instruction,
)
from yoke_core.domain.workflow_execution_instructions import (
    resolve_execution_instructions,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def test_new_project_receives_shipped_board_and_execution_instruction(
    tmp_path: Path,
) -> None:
    with init_test_db(tmp_path):
        cmd_create("acme-defaults", "Acme", public_item_prefix="ACME")
        conn = connect_test_db(str(tmp_path / "yoke.db"))
        try:
            project_id = int(
                conn.execute(
                    "SELECT id FROM projects WHERE slug = %s",
                    ("acme-defaults",),
                ).fetchone()[0]
            )
            settings = load_project_policy_settings(conn, project_id)
            board = settings["board"]
            defaults = BoardConfig()
            for key in (
                "done_section_limit",
                "timeline_label_days",
                "timeline_label_df_cap_pct",
                "timeline_label_min",
                "timeline_widget",
                "dashboard_weather",
                "dashboard_velocity_meter",
                "art_weight_frontier",
                "art_frontier_since",
            ):
                assert board[key] == getattr(defaults, key)
            assert board["done_section_limit"] == 20
            assert board["timeline_widget"] == "always"
            assert board["dashboard_weather"] is False
            assert board["art_frontier_since"] == 0
            assert "disposable_generated_paths" not in settings

            resolved = resolve_execution_instructions(
                conn, workflow_id="dash", project_id=project_id
            )
            assert [row["content"] for row in resolved] == [
                SHIPPED_EXECUTION_INSTRUCTION
            ]
            assert resolved[0]["applies_to_all_projects"] is True
            assert resolved[0]["applies_to_all_workflows"] is False
            assert (
                resolve_execution_instructions(
                    conn, workflow_id="task", project_id=project_id
                )
                == []
            )

            seed_shipped_execution_instruction(conn)
            count = conn.execute(
                "SELECT COUNT(*) FROM workflow_execution_instructions"
            ).fetchone()[0]
            assert int(count) == 1
            bound = [
                row[0]
                for row in conn.execute(
                    "SELECT workflow_id FROM workflow_execution_instruction_workflows "
                    "WHERE instruction_id = %s ORDER BY workflow_id",
                    (resolved[0]["id"],),
                ).fetchall()
            ]
            assert bound == list(SHIPPED_WORKFLOW_IDS)
        finally:
            conn.close()
