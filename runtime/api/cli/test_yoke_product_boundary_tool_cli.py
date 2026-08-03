from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory


def test_teaching_audit_accepts_tool_cli_watcher_commands(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "recipe.md").write_text(
        "```bash\nyoke watch pytest -- runtime/api/\n```\n",
        encoding="utf-8",
    )
    audit = inventory.generate_teaching_audit(repo_root=tmp_path)
    assert len(audit.surfaces) == 1
    surface = audit.surfaces[0]
    assert surface.command_form == "yoke watch pytest"
    assert surface.resolution == "tool_shaped"
    assert surface.status == "tool_cli"
    assert surface.reason == "tool_shaped"
    assert surface.drift_type is None
